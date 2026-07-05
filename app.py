import os
import json
import sqlite3
from flask import Flask, render_template, request, jsonify
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
import logging
from job_scraper import LinkedInScraper
from ai_processor import JobAIProcessor
from database import Database

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'dev-key-123')

db = Database()
ai_processor = JobAIProcessor()
scraper = LinkedInScraper()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global flag for scan status
scan_running = False

def morning_job_scan():
    """Run at 8 AM daily"""
    global scan_running
    if scan_running:
        logger.info("Scan already running, skipping")
        return
    
    try:
        scan_running = True
        logger.info("Starting scheduled morning scan...")
        jobs = scraper.scrape_last_24_hours()
        logger.info(f"Found {len(jobs)} jobs")
        
        # Only process top 10 jobs to avoid timeout
        jobs_to_process = jobs[:10]
        saved_count = 0
        
        for job in jobs_to_process:
            job_id = job.get('id', f"job_{datetime.now().timestamp()}")
            if db.job_exists(job_id):
                continue
            result = ai_processor.process_job(job)
            db.save_job({
                'job_id': job_id,
                'title': job.get('title', 'Unknown Position'),
                'company': job.get('company', 'Unknown Company'),
                'description': job.get('description', ''),
                'match_score': result['match_score'],
                'assessment': result['assessment'],
                'tailored_cv': result['tailored_cv'],
                'cover_letter': result['cover_letter'],
                'answers': json.dumps(result['answers']),
                'url': job.get('url', ''),
                'processed_at': datetime.now().isoformat()
            })
            saved_count += 1
        
        logger.info(f"Morning scan completed - saved {saved_count} new jobs")
    except Exception as e:
        logger.error(f"Morning scan failed: {e}")
    finally:
        scan_running = False

# Setup scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(
    morning_job_scan,
    trigger=CronTrigger(hour=8, minute=0),
    id='morning_scan',
    replace_existing=True
)
scheduler.start()

@app.route('/')
def dashboard():
    jobs = db.get_todays_jobs()
    logger.info(f"Dashboard loaded with {len(jobs)} jobs")
    return render_template('dashboard.html', jobs=jobs)

@app.route('/api/jobs')
def get_jobs():
    jobs = db.get_todays_jobs()
    return jsonify(jobs)

@app.route('/api/apply/<job_id>')
def apply_job(job_id):
    job = db.get_job(job_id)
    if job:
        return jsonify({
            'cv': job.get('tailored_cv', ''),
            'cover_letter': job.get('cover_letter', ''),
            'answers': json.loads(job.get('answers', '{}'))
        })
    return jsonify({'error': 'Job not found'}), 404

@app.route('/api/refresh')
def refresh_jobs():
    """Manual refresh - scrapes directly"""
    global scan_running
    if scan_running:
        return jsonify({'status': 'error', 'message': 'Scan already running'}), 400
    
    try:
        scan_running = True
        logger.info("Starting manual refresh...")
        jobs = scraper.scrape_last_24_hours()
        logger.info(f"Found {len(jobs)} jobs from scraper")
        
        if not jobs:
            scan_running = False
            return jsonify({'status': 'success', 'jobs_found': 0, 'saved': 0, 'message': 'No jobs found'})
        
        # Only process top 5 jobs to avoid timeout
        jobs_to_process = jobs[:5]
        logger.info(f"Processing first {len(jobs_to_process)} jobs (out of {len(jobs)} total)")
        
        saved_count = 0
        for job in jobs_to_process:
            try:
                job_id = job.get('id')
                if not job_id:
                    job_id = f"job_{datetime.now().timestamp()}_{abs(hash(job.get('url', '')))}"
                
                if db.job_exists(str(job_id)):
                    logger.info(f"Job {job_id} already exists, skipping")
                    continue
                
                logger.info(f"Processing: {job.get('title')} at {job.get('company')}")
                result = ai_processor.process_job(job)
                
                db.save_job({
                    'job_id': str(job_id),
                    'title': job.get('title', 'Unknown Position'),
                    'company': job.get('company', 'Unknown Company'),
                    'description': job.get('description', ''),
                    'match_score': result['match_score'],
                    'assessment': result['assessment'],
                    'tailored_cv': result['tailored_cv'],
                    'cover_letter': result['cover_letter'],
                    'answers': json.dumps(result['answers']),
                    'url': job.get('url', ''),
                    'processed_at': datetime.now().isoformat()
                })
                saved_count += 1
                logger.info(f"Saved job #{saved_count}: {job.get('title')}")
                
            except Exception as e:
                logger.error(f"Error processing job: {e}")
                continue
        
        scan_running = False
        logger.info(f"Manual refresh completed - saved {saved_count} new jobs")
        return jsonify({
            'status': 'success',
            'jobs_found': len(jobs),
            'saved': saved_count,
            'message': f'Found {len(jobs)} jobs, saved {saved_count} new ones (processed {len(jobs_to_process)})'
        })
        
    except Exception as e:
        logger.error(f"Refresh error: {e}")
        scan_running = False
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/status')
def scan_status():
    return jsonify({'scan_running': scan_running})

@app.route('/api/debug-db')
def debug_db():
    """Debug endpoint to check database"""
    try:
        conn = sqlite3.connect('data/jobs.db')
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM jobs")
        count = cursor.fetchone()[0]
        cursor.execute("SELECT job_id, title, company, match_score, created_at FROM jobs ORDER BY created_at DESC LIMIT 10")
        rows = cursor.fetchall()
        conn.close()
        return jsonify({
            'total_jobs': count,
            'recent_jobs': [{'job_id': r[0], 'title': r[1], 'company': r[2], 'match_score': r[3], 'created_at': r[4]} for r in rows]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/all-jobs')
def all_jobs():
    """Show ALL jobs in database (ignore date)"""
    try:
        conn = sqlite3.connect('data/jobs.db')
        cursor = conn.cursor()
        cursor.execute("SELECT job_id, title, company, match_score, processed_at FROM jobs ORDER BY created_at DESC LIMIT 50")
        rows = cursor.fetchall()
        conn.close()
        return jsonify({
            'total': len(rows),
            'jobs': [{'job_id': r[0], 'title': r[1], 'company': r[2], 'match_score': r[3], 'processed_at': r[4]} for r in rows]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

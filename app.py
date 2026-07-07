import os
import json
import sqlite3
from flask import Flask, render_template, request, jsonify
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
import logging
import threading
from job_scraper import LinkedInScraper
from ai_processor import JobAIProcessor
from database import Database
from cv_matcher import CVMatchingAgent

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'dev-key-123')

db = Database()
ai_processor = JobAIProcessor()
scraper = LinkedInScraper()
cv_matcher = CVMatchingAgent()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scan_running = False

def process_jobs_in_background(jobs):
    """Process jobs in the background with a timeout-safe approach"""
    try:
        saved_count = 0
        total_processed = 0
        
        for job in jobs:
            try:
                total_processed += 1
                job_id = job.get('id')
                if not job_id:
                    job_id = f"job_{datetime.now().timestamp()}_{abs(hash(job.get('url', '')))}"
                
                if db.job_exists(str(job_id)):
                    logger.info(f"Job {job_id} already exists, skipping")
                    continue
                
                logger.info(f"Processing job {total_processed}: {job.get('title')} at {job.get('company')}")
                result = ai_processor.process_job(job)
                
                cv_score = job.get('cv_match_score', 0)
                matched_template = job.get('matched_template', '')
                
                db.save_job({
                    'job_id': str(job_id),
                    'title': job.get('title', 'Unknown Position'),
                    'company': job.get('company', 'Unknown Company'),
                    'description': job.get('description', ''),
                    'match_score': result['match_score'],
                    'cv_match_score': cv_score,
                    'matched_template': matched_template,
                    'assessment': result['assessment'],
                    'tailored_cv': result['tailored_cv'],
                    'cover_letter': result['cover_letter'],
                    'answers': json.dumps(result['answers']),
                    'url': job.get('url', ''),
                    'processed_at': datetime.now().isoformat()
                })
                saved_count += 1
                logger.info(f"Saved job #{saved_count}: {job.get('title')} (CV Match: {cv_score}%)")
                
            except Exception as e:
                logger.error(f"Error processing job: {e}")
                continue
        
        logger.info(f"Background processing complete: {saved_count} new jobs saved out of {total_processed} processed")
    except Exception as e:
        logger.error(f"Background processing error: {e}")
    finally:
        global scan_running
        scan_running = False

@app.route('/api/refresh')
def refresh_jobs():
    """Manual refresh - scrapes and filters by CV match"""
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
        
        # FILTER by JD template match - threshold 0.30 (30% similarity)
        matched_jobs = cv_matcher.filter_jobs_by_template_match(jobs, threshold=0.30)
        logger.info(f"Filtered to {len(matched_jobs)} matched jobs")
        
        thread = threading.Thread(target=process_jobs_in_background, args=(matched_jobs,))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'success',
            'jobs_found': len(jobs),
            'matched': len(matched_jobs),
            'templates': cv_matcher.list_templates(),
            'message': f'Found {len(jobs)} jobs, {len(matched_jobs)} matched your target roles - processing in background'
        })
        
    except Exception as e:
        logger.error(f"Refresh error: {e}")
        scan_running = False
        return jsonify({'status': 'error', 'message': str(e)}), 500

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
        
        matched_jobs = cv_matcher.filter_jobs_by_template_match(jobs, threshold=0.30)
        logger.info(f"Filtered to {len(matched_jobs)} matched jobs")
        
        thread = threading.Thread(target=process_jobs_in_background, args=(matched_jobs,))
        thread.daemon = True
        thread.start()
        
    except Exception as e:
        logger.error(f"Morning scan failed: {e}")
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
    """Get application materials for a specific job - FIXED JSON parsing"""
    try:
        logger.info(f"Fetching job with ID: {job_id}")
        job = db.get_job(job_id)
        if job:
            # Handle answers - it could be a dict, string, or None
            answers = job.get('answers', {})
            if isinstance(answers, str):
                try:
                    answers = json.loads(answers)
                except:
                    answers = {}
            elif not isinstance(answers, dict):
                answers = {}
            
            return jsonify({
                'cv': job.get('tailored_cv', 'No CV available'),
                'cover_letter': job.get('cover_letter', 'No cover letter available'),
                'answers': answers
            })
        else:
            all_jobs = db.get_todays_jobs()
            if all_jobs:
                first_job = all_jobs[0]
                answers = first_job.get('answers', {})
                if isinstance(answers, str):
                    try:
                        answers = json.loads(answers)
                    except:
                        answers = {}
                return jsonify({
                    'cv': first_job.get('tailored_cv', 'CV not found - run a new scan'),
                    'cover_letter': first_job.get('cover_letter', 'Cover letter not found - run a new scan'),
                    'answers': answers
                })
            return jsonify({
                'cv': 'No jobs found. Please run a new scan first.',
                'cover_letter': 'No jobs found. Please run a new scan first.',
                'answers': {}
            })
    except Exception as e:
        logger.error(f"Apply error: {e}")
        return jsonify({
            'cv': f'Error: {str(e)}',
            'cover_letter': 'Please try again',
            'answers': {}
        })

@app.route('/api/status')
def scan_status():
    return jsonify({'scan_running': scan_running})

@app.route('/api/templates')
def list_templates():
    return jsonify({'templates': cv_matcher.list_templates()})

@app.route('/api/debug-db')
def debug_db():
    try:
        conn = sqlite3.connect('data/jobs.db')
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM jobs")
        count = cursor.fetchone()[0]
        cursor.execute("SELECT job_id, title, company, match_score, cv_match_score, matched_template, created_at FROM jobs ORDER BY created_at DESC LIMIT 10")
        rows = cursor.fetchall()
        conn.close()
        return jsonify({
            'total_jobs': count,
            'recent_jobs': [{'job_id': r[0], 'title': r[1], 'company': r[2], 'match_score': r[3], 'cv_match_score': r[4], 'matched_template': r[5], 'created_at': r[6]} for r in rows]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/all-jobs')
def all_jobs():
    try:
        conn = sqlite3.connect('data/jobs.db')
        cursor = conn.cursor()
        cursor.execute("SELECT job_id, title, company, match_score, cv_match_score, processed_at FROM jobs ORDER BY created_at DESC LIMIT 50")
        rows = cursor.fetchall()
        conn.close()
        return jsonify({
            'total': len(rows),
            'jobs': [{'job_id': r[0], 'title': r[1], 'company': r[2], 'match_score': r[3], 'cv_match_score': r[4], 'processed_at': r[5]} for r in rows]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

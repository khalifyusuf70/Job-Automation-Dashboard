import os
import json
from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
import logging
import threading
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

# Global flag to track if a scan is running
scan_running = False

def run_scan_in_background():
    """Run the job scan as a background task"""
    global scan_running
    try:
        scan_running = True
        logger.info("Starting background job scan...")
        
        # Check if we already have jobs from today
        existing_jobs = db.get_todays_jobs()
        if existing_jobs:
            logger.info(f"Already have {len(existing_jobs)} jobs from today - skipping duplicate scrape")
            scan_running = False
            return
            
        jobs = scraper.scrape_last_24_hours()
        logger.info(f"Found {len(jobs)} new jobs")
        
        for job in jobs:
            if db.job_exists(job['id']):
                continue
            result = ai_processor.process_job(job)
            db.save_job({
                'job_id': job['id'],
                'title': job['title'],
                'company': job['company'],
                'description': job['description'],
                'match_score': result['match_score'],
                'assessment': result['assessment'],
                'tailored_cv': result['tailored_cv'],
                'cover_letter': result['cover_letter'],
                'answers': json.dumps(result['answers']),
                'url': job['url'],
                'processed_at': datetime.now().isoformat()
            })
        logger.info("Background scan completed successfully")
    except Exception as e:
        logger.error(f"Background scan failed: {e}")
    finally:
        scan_running = False

def morning_job_scan():
    """Triggered by scheduler at 8 AM - runs in background"""
    # Run in a separate thread to not block the scheduler
    thread = threading.Thread(target=run_scan_in_background)
    thread.daemon = True
    thread.start()

# Schedule once per day at 8 AM
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
    return render_template('dashboard.html', jobs=jobs, scan_running=scan_running)

@app.route('/api/jobs')
def get_jobs():
    jobs = db.get_todays_jobs()
    return jsonify(jobs)

@app.route('/api/apply/<job_id>')
def apply_job(job_id):
    job = db.get_job(job_id)
    if job:
        return jsonify({
            'cv': job['tailored_cv'],
            'cover_letter': job['cover_letter'],
            'answers': json.loads(job['answers'])
        })
    return jsonify({'error': 'Job not found'}), 404

@app.route('/api/refresh')
def refresh_jobs():
    """Trigger a manual refresh - runs in background"""
    global scan_running
    if scan_running:
        return jsonify({'status': 'Scan already running, please wait'})
    
    # Start the scan in background
    thread = threading.Thread(target=run_scan_in_background)
    thread.daemon = True
    thread.start()
    return jsonify({'status': 'Scan started in background. Check logs for progress.'})

@app.route('/api/status')
def scan_status():
    """Check if a scan is running"""
    return jsonify({'scan_running': scan_running})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

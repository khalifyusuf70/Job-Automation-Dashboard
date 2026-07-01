import os
import json
from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
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

scheduler = BackgroundScheduler()

def morning_job_scan():
    """Run once per day at 8 AM - this is the ONLY time we scrape"""
    logger.info("Starting morning job scan...")
    try:
        # Check if we already have jobs from today
        existing_jobs = db.get_todays_jobs()
        if existing_jobs:
            logger.info(f"Already have {len(existing_jobs)} jobs from today - skipping duplicate scrape")
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
        logger.info("Morning scan completed successfully")
    except Exception as e:
        logger.error(f"Morning scan failed: {e}")

# Schedule once per day at 8 AM
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
            'cv': job['tailored_cv'],
            'cover_letter': job['cover_letter'],
            'answers': json.loads(job['answers'])
        })
    return jsonify({'error': 'Job not found'}), 404

@app.route('/api/refresh')
def refresh_jobs():
    """Refresh endpoint now just returns today's jobs without re-scraping"""
    jobs = db.get_todays_jobs()
    if not jobs:
        # Only scrape if no jobs exist yet today
        morning_job_scan()
        return jsonify({'status': 'No jobs found for today - triggered fresh scan'})
    else:
        return jsonify({'status': f'Already have {len(jobs)} jobs from today - no new scrape needed'})

# New endpoint to force a fresh scrape (use sparingly!)
@app.route('/api/force-scrape')
def force_scrape():
    """Emergency endpoint to force a fresh scrape - use only when needed"""
    if request.args.get('secret') == os.getenv('FORCE_SECRET', 'emergency'):
        morning_job_scan()
        return jsonify({'status': 'Force scrape triggered'})
    return jsonify({'error': 'Unauthorized'}), 403

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

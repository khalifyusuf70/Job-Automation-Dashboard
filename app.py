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

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'dev-key-123')

# Initialize components
db = Database()
ai_processor = JobAIProcessor()
scraper = LinkedInScraper()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Background scheduler for morning automation
scheduler = BackgroundScheduler()

def morning_job_scan():
    """Run every morning at 8 AM"""
    logger.info("Starting morning job scan...")
    try:
        # 1. Scrape jobs from last 24 hours
        jobs = scraper.scrape_last_24_hours()
        logger.info(f"Found {len(jobs)} new jobs")
        
        # 2. Process each job with AI
        for job in jobs:
            # Check if already processed
            if db.job_exists(job['id']):
                continue
                
            # Process with AI
            result = ai_processor.process_job(job)
            
            # Save to database
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

# Schedule the morning job
scheduler.add_job(
    morning_job_scan,
    trigger=CronTrigger(hour=8, minute=0),  # 8 AM daily
    id='morning_scan',
    replace_existing=True
)
scheduler.start()

@app.route('/')
def dashboard():
    """Display the main dashboard"""
    jobs = db.get_todays_jobs()
    return render_template('dashboard.html', jobs=jobs)

@app.route('/api/jobs')
def get_jobs():
    """API endpoint for jobs"""
    jobs = db.get_todays_jobs()
    return jsonify(jobs)

@app.route('/api/apply/<job_id>')
def apply_job(job_id):
    """Get application materials for a specific job"""
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
    """Manually trigger job scan"""
    morning_job_scan()
    return jsonify({'status': 'Scan started'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

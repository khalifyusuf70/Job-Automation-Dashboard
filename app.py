import os
import json
import sqlite3
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

# Try to load CV Matcher - gracefully handle failure
try:
    from cv_matcher import CVMatchingAgent
    cv_matcher = CVMatchingAgent()
    logger.info("CVMatchingAgent loaded successfully")
except Exception as e:
    logger.error(f"Failed to load CVMatchingAgent: {e}")
    cv_matcher = None
    logger.warning("CV matching disabled - all jobs will be processed")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scan_running = False
backfill_running = False

def process_jobs_in_background(jobs, source="daily"):
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
                    'processed_at': datetime.now().isoformat(),
                    'cv_edited': '',
                    'cover_letter_edited': '',
                    'applied': 0,
                    'deleted': 0
                })
                saved_count += 1
                logger.info(f"Saved job #{saved_count}: {job.get('title')} (CV Match: {cv_score}%)")
                
            except Exception as e:
                logger.error(f"Error processing job: {e}")
                continue
        
        logger.info(f"Background processing complete: {saved_count} new jobs saved out of {total_processed} processed ({source})")
        return saved_count
    except Exception as e:
        logger.error(f"Background processing error: {e}")
        return 0
    finally:
        global scan_running, backfill_running
        if source == "daily":
            scan_running = False
        else:
            backfill_running = False

# ============ BACKFILL FUNCTIONS ============

def run_custom_backfill_batch(start_date, end_date, location="Kenya", max_items=500, threshold=0.30):
    """
    Run a single backfill batch for a specific date range
    
    Args:
        start_date: datetime object for start of range
        end_date: datetime object for end of range
        location: "Kenya", "Somalia", or "Kenya, Somalia"
        max_items: max jobs to fetch (default 500)
        threshold: CV match threshold (default 0.30)
    
    Returns:
        list: matched jobs
    """
    try:
        # Calculate days between dates
        delta = end_date - start_date
        days = delta.days
        
        if days <= 0:
            logger.warning(f"Invalid date range: {start_date} to {end_date}")
            return []
        
        # Calculate seconds for f_TPR
        seconds = int(delta.total_seconds())
        f_tpr_value = f"r{seconds}"
        
        logger.info(f"Running custom backfill: {start_date.date()} to {end_date.date()} ({days} days, {f_tpr_value})")
        
        # Build the search URL
        keyword = 'Director%20OR%20Executive%20OR%20Manager%20OR%20Senior%20OR%20%22Head%20of%22%20OR%20Lead%20OR%20Advisor%20OR%20Consultant%20OR%20Coordinator%20OR%20Specialist'
        location_encoded = location.replace(", ", "%2C%20").replace(" ", "%20")
        
        start_url = f"https://www.linkedin.com/jobs/search/?f_TPR={f_tpr_value}&keywords={keyword}&location={location_encoded}"
        
        # Scrape using the custom URL
        jobs = scraper.scrape_with_custom_url(start_url, max_items=max_items)
        logger.info(f"Found {len(jobs)} raw jobs in batch")
        
        if not jobs:
            return []
        
        # Filter by CV match - if cv_matcher is available
        if cv_matcher is not None:
            matched_jobs = cv_matcher.filter_jobs_by_template_match(jobs, threshold=threshold)
            logger.info(f"Filtered to {len(matched_jobs)} matched jobs in batch")
            return matched_jobs
        else:
            logger.info("CV matching disabled - returning all jobs")
            return jobs
        
    except Exception as e:
        logger.error(f"Custom backfill batch error: {e}")
        return []

def run_full_backfill_60_days(location="Kenya", max_items=500, threshold=0.30):
    """
    Run a full 60-day backfill in 10-day batches
    
    Args:
        location: "Kenya", "Somalia", or "Kenya, Somalia"
        max_items: max jobs per batch
        threshold: CV match threshold
    """
    global backfill_running
    if backfill_running:
        logger.info("Backfill already running, skipping")
        return
    
    try:
        backfill_running = True
        logger.info("Starting full 60-day backfill...")
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=60)
        
        all_matched_jobs = []
        batch_size = 10  # 10 days per batch
        batches_run = 0
        
        current_end = end_date
        
        while current_end > start_date:
            current_start = current_end - timedelta(days=batch_size)
            if current_start < start_date:
                current_start = start_date
            
            logger.info(f"Running backfill batch {batches_run + 1}: {current_start.date()} to {current_end.date()}")
            
            batch_jobs = run_custom_backfill_batch(current_start, current_end, location, max_items, threshold)
            all_matched_jobs.extend(batch_jobs)
            batches_run += 1
            
            # Move to next batch
            current_end = current_start - timedelta(days=1)
            
            # Small delay between batches
            import time
            time.sleep(2)
        
        logger.info(f"Full backfill complete: {len(all_matched_jobs)} matched jobs across {batches_run} batches")
        
        # Process all matched jobs
        if all_matched_jobs:
            saved = process_jobs_in_background(all_matched_jobs, "backfill")
            logger.info(f"Saved {saved} new jobs from backfill")
        else:
            logger.info("No matched jobs found in backfill")
            
    except Exception as e:
        logger.error(f"Full backfill error: {e}")
    finally:
        backfill_running = False

# ============ API ENDPOINTS ============

@app.route('/api/refresh')
def refresh_jobs():
    """Manual refresh - scrapes and filters by CV match (daily)"""
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
        
        # FILTER by CV match - if cv_matcher is available
        if cv_matcher is not None:
            matched_jobs = cv_matcher.filter_jobs_by_template_match(jobs, threshold=0.30)
            logger.info(f"Filtered to {len(matched_jobs)} matched jobs")
        else:
            matched_jobs = jobs
            logger.info("CV matching disabled - processing all jobs")
        
        thread = threading.Thread(target=process_jobs_in_background, args=(matched_jobs, "daily"))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'success',
            'jobs_found': len(jobs),
            'matched': len(matched_jobs),
            'templates': cv_matcher.list_templates() if cv_matcher else [],
            'message': f'Found {len(jobs)} jobs, {len(matched_jobs)} matched your target roles - processing in background'
        })
        
    except Exception as e:
        logger.error(f"Refresh error: {e}")
        scan_running = False
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/backfill')
def trigger_backfill():
    """Trigger a full 60-day backfill in 10-day batches"""
    global backfill_running
    if backfill_running:
        return jsonify({'status': 'error', 'message': 'Backfill already running'}), 400
    
    # Get parameters from query string (optional)
    location = request.args.get('location', 'Kenya')
    max_items = int(request.args.get('max_items', 500))
    threshold = float(request.args.get('threshold', 0.30))
    days = int(request.args.get('days', 60))
    
    # Validate
    if days > 90:
        return jsonify({'status': 'error', 'message': 'Days cannot exceed 90'}), 400
    
    # Run in background
    thread = threading.Thread(target=run_full_backfill_60_days, args=(location, max_items, threshold))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'status': 'success',
        'message': f'Backfill started for last {days} days in 10-day batches! Check logs for progress.',
        'params': {
            'location': location,
            'max_items': max_items,
            'threshold': threshold,
            'days': days
        }
    })

@app.route('/api/backfill/custom')
def trigger_custom_backfill():
    """Trigger a custom backfill with specific date ranges"""
    global backfill_running
    if backfill_running:
        return jsonify({'status': 'error', 'message': 'Backfill already running'}), 400
    
    try:
        # Get parameters from query string
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        location = request.args.get('location', 'Kenya')
        max_items = int(request.args.get('max_items', 500))
        threshold = float(request.args.get('threshold', 0.30))
        batch_size = int(request.args.get('batch_size', 10))
        
        # Validate dates
        if not start_date_str or not end_date_str:
            return jsonify({'status': 'error', 'message': 'start_date and end_date are required (format: YYYY-MM-DD)'}), 400
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        
        if start_date > end_date:
            return jsonify({'status': 'error', 'message': 'start_date must be before end_date'}), 400
        
        # Run in background
        def run_custom_backfill():
            global backfill_running
            backfill_running = True
            try:
                all_matched_jobs = []
                batches_run = 0
                current_end = end_date
                
                while current_end > start_date:
                    current_start = current_end - timedelta(days=batch_size)
                    if current_start < start_date:
                        current_start = start_date
                    
                    logger.info(f"Running custom batch {batches_run + 1}: {current_start.date()} to {current_end.date()}")
                    
                    batch_jobs = run_custom_backfill_batch(current_start, current_end, location, max_items, threshold)
                    all_matched_jobs.extend(batch_jobs)
                    batches_run += 1
                    
                    current_end = current_start - timedelta(days=1)
                    import time
                    time.sleep(2)
                
                logger.info(f"Custom backfill complete: {len(all_matched_jobs)} matched jobs across {batches_run} batches")
                
                if all_matched_jobs:
                    saved = process_jobs_in_background(all_matched_jobs, "backfill")
                    logger.info(f"Saved {saved} new jobs from custom backfill")
                else:
                    logger.info("No matched jobs found in custom backfill")
                    
            except Exception as e:
                logger.error(f"Custom backfill error: {e}")
            finally:
                backfill_running = False
        
        thread = threading.Thread(target=run_custom_backfill)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'success',
            'message': f'Custom backfill started for {start_date.date()} to {end_date.date()} in {batch_size}-day batches!',
            'params': {
                'start_date': start_date.date().isoformat(),
                'end_date': end_date.date().isoformat(),
                'location': location,
                'max_items': max_items,
                'threshold': threshold,
                'batch_size': batch_size
            }
        })
        
    except Exception as e:
        logger.error(f"Custom backfill error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/backfill/status')
def backfill_status():
    return jsonify({'backfill_running': backfill_running})

def morning_job_scan():
    """Run at 8 AM daily - adds new jobs to existing ones"""
    global scan_running
    if scan_running:
        logger.info("Scan already running, skipping")
        return
    
    try:
        scan_running = True
        logger.info("Starting scheduled morning scan...")
        jobs = scraper.scrape_last_24_hours()
        logger.info(f"Found {len(jobs)} jobs")
        
        if cv_matcher is not None:
            matched_jobs = cv_matcher.filter_jobs_by_template_match(jobs, threshold=0.30)
            logger.info(f"Filtered to {len(matched_jobs)} matched jobs")
        else:
            matched_jobs = jobs
            logger.info("CV matching disabled - processing all jobs")
        
        thread = threading.Thread(target=process_jobs_in_background, args=(matched_jobs, "daily"))
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
    jobs = db.get_all_active_jobs()
    logger.info(f"Dashboard loaded with {len(jobs)} active jobs")
    return render_template('dashboard.html', jobs=jobs)

@app.route('/api/jobs')
def get_jobs():
    jobs = db.get_all_active_jobs()
    return jsonify(jobs)

@app.route('/api/delete/<job_id>', methods=['POST'])
def delete_job(job_id):
    try:
        success = db.delete_job(job_id)
        if success:
            return jsonify({'status': 'success', 'message': 'Job deleted successfully'})
        else:
            return jsonify({'status': 'error', 'message': 'Job not found'}), 404
    except Exception as e:
        logger.error(f"Delete error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/apply-now/<job_id>', methods=['POST'])
def mark_applied(job_id):
    try:
        success = db.mark_applied(job_id)
        if success:
            return jsonify({'status': 'success', 'message': 'Job marked as applied'})
        else:
            return jsonify({'status': 'error', 'message': 'Job not found'}), 404
    except Exception as e:
        logger.error(f"Mark applied error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/apply/<job_id>')
def apply_job(job_id):
    try:
        logger.info(f"Fetching job with ID: {job_id}")
        job = db.get_job(job_id)
        if job:
            answers = job.get('answers', {})
            if isinstance(answers, str):
                try:
                    answers = json.loads(answers)
                except:
                    answers = {}
            elif not isinstance(answers, dict):
                answers = {}
            
            cv = job.get('cv_edited') or job.get('tailored_cv', 'No CV available')
            cover_letter = job.get('cover_letter_edited') or job.get('cover_letter', 'No cover letter available')
            
            return jsonify({
                'cv': cv,
                'cover_letter': cover_letter,
                'answers': answers,
                'original_cv': job.get('tailored_cv', ''),
                'original_cover_letter': job.get('cover_letter', '')
            })
        else:
            all_jobs = db.get_all_active_jobs()
            if all_jobs:
                first_job = all_jobs[0]
                answers = first_job.get('answers', {})
                if isinstance(answers, str):
                    try:
                        answers = json.loads(answers)
                    except:
                        answers = {}
                cv = first_job.get('cv_edited') or first_job.get('tailored_cv', 'CV not found')
                cover_letter = first_job.get('cover_letter_edited') or first_job.get('cover_letter', 'Cover letter not found')
                return jsonify({
                    'cv': cv,
                    'cover_letter': cover_letter,
                    'answers': answers,
                    'original_cv': first_job.get('tailored_cv', ''),
                    'original_cover_letter': first_job.get('cover_letter', '')
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

@app.route('/api/save-edits/<job_id>', methods=['POST'])
def save_edits(job_id):
    try:
        data = request.get_json()
        cv_edited = data.get('cv', '')
        cover_letter_edited = data.get('cover_letter', '')
        
        logger.info(f"Saving edits for job: {job_id}")
        
        conn = sqlite3.connect('data/jobs.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE jobs 
            SET cv_edited = ?, cover_letter_edited = ?
            WHERE job_id = ? OR id = ?
        ''', (cv_edited, cover_letter_edited, str(job_id), str(job_id)))
        conn.commit()
        conn.close()
        
        logger.info(f"Edits saved for job: {job_id}")
        return jsonify({'status': 'success', 'message': 'Changes saved successfully!'})
        
    except Exception as e:
        logger.error(f"Error saving edits: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/status')
def scan_status():
    return jsonify({'scan_running': scan_running})

@app.route('/api/templates')
def list_templates():
    if cv_matcher:
        return jsonify({'templates': cv_matcher.list_templates()})
    else:
        return jsonify({'templates': [], 'error': 'CV matcher not available'})

@app.route('/api/debug-db')
def debug_db():
    try:
        conn = sqlite3.connect('data/jobs.db')
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM jobs WHERE deleted = 0")
        count = cursor.fetchone()[0]
        cursor.execute("SELECT job_id, title, company, match_score, cv_match_score, applied, created_at FROM jobs WHERE deleted = 0 ORDER BY created_at DESC LIMIT 10")
        rows = cursor.fetchall()
        conn.close()
        return jsonify({
            'total_active_jobs': count,
            'recent_jobs': [{'job_id': r[0], 'title': r[1], 'company': r[2], 'match_score': r[3], 'cv_match_score': r[4], 'applied': r[5], 'created_at': r[6]} for r in rows]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

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
import traceback

# ============ LOGGER MUST BE DEFINED FIRST ============
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ NOW IMPORT OTHER MODULES ============
from job_scraper import LinkedInScraper
from ai_processor import JobAIProcessor
from database import Database

# Try to import CV matcher - continue if it fails
try:
    from cv_matcher import CVMatchingAgent
    cv_matcher = CVMatchingAgent()
    logger.info("CV Matcher initialized successfully")
except Exception as e:
    logger.error(f"CV Matcher initialization failed: {e}")
    cv_matcher = None

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'dev-key-123')

# ============ INITIALIZE COMPONENTS ============
try:
    db = Database()
    logger.info("Database initialized successfully")
except Exception as e:
    logger.error(f"Database initialization failed: {e}")
    db = None

try:
    ai_processor = JobAIProcessor()
    logger.info("AI Processor initialized successfully")
except Exception as e:
    logger.error(f"AI Processor initialization failed: {e}")
    ai_processor = None

try:
    scraper = LinkedInScraper()
    logger.info("LinkedIn Scraper initialized successfully")
except Exception as e:
    logger.error(f"LinkedIn Scraper initialization failed: {e}")
    scraper = None

# ============ GLOBAL FLAGS ============
scan_running = False
backfill_running = False

def process_jobs_in_background(jobs, source="daily"):
    """Process jobs in the background"""
    if not jobs:
        logger.info("No jobs to process")
        return
        
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
    except Exception as e:
        logger.error(f"Background processing error: {e}")
    finally:
        global scan_running, backfill_running
        if source == "daily":
            scan_running = False
        else:
            backfill_running = False

# ============ BACKFILL FUNCTIONS ============

def run_backfill_batch(start_date, end_date):
    """Run a single backfill batch for a date range"""
    try:
        delta = end_date - start_date
        seconds = int(delta.total_seconds())
        f_tpr_value = f"r{seconds}"
        
        logger.info(f"Running backfill batch: {start_date.date()} to {end_date.date()} ({f_tpr_value})")
        
        start_url = f"https://www.linkedin.com/jobs/search/?f_TPR={f_tpr_value}&keywords=Director%20OR%20Executive%20OR%20Manager"
        
        jobs = scraper.scrape_with_custom_url(start_url)
        logger.info(f"Found {len(jobs)} jobs in backfill batch")
        
        if jobs and cv_matcher:
            matched_jobs = cv_matcher.filter_jobs_by_template_match(jobs, threshold=0.30)
            logger.info(f"Filtered to {len(matched_jobs)} matched jobs in backfill batch")
            return matched_jobs
        return jobs
        
    except Exception as e:
        logger.error(f"Backfill batch error: {e}")
        return []

def run_full_backfill():
    """Run backfill for the last 60 days in 10-day batches"""
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
        batch_size = 10
        batches_run = 0
        
        current_end = end_date
        
        while current_end > start_date:
            current_start = current_end - timedelta(days=batch_size)
            if current_start < start_date:
                current_start = start_date
            
            logger.info(f"Running backfill batch {batches_run + 1}: {current_start.date()} to {current_end.date()}")
            
            batch_jobs = run_backfill_batch(current_start, current_end)
            all_matched_jobs.extend(batch_jobs)
            batches_run += 1
            
            current_end = current_start - timedelta(days=1)
            
            import time
            time.sleep(2)
        
        logger.info(f"Full backfill complete: {len(all_matched_jobs)} matched jobs across {batches_run} batches")
        
        if all_matched_jobs:
            thread = threading.Thread(target=process_jobs_in_background, args=(all_matched_jobs, "backfill"))
            thread.daemon = True
            thread.start()
            logger.info(f"Started processing {len(all_matched_jobs)} backfill jobs")
        else:
            logger.info("No matched jobs found in backfill")
            
    except Exception as e:
        logger.error(f"Full backfill error: {e}")
    finally:
        backfill_running = False

# ============ API ENDPOINTS ============

@app.route('/')
def dashboard():
    """Dashboard - shows all active jobs with graceful error handling"""
    try:
        # Check if database is initialized
        if db is None:
            logger.error("Database not initialized!")
            return """
            <h1>⚠️ Database Error</h1>
            <p>Database not initialized. Please check the logs.</p>
            <p><a href="/api/debug-db">Check Database Status</a></p>
            """, 500
        
        # Get all active jobs
        jobs = db.get_all_active_jobs()
        logger.info(f"Dashboard loaded with {len(jobs)} active jobs")
        return render_template('dashboard.html', jobs=jobs)
        
    except AttributeError as e:
        # Missing method in database - try to reinitialize
        logger.error(f"Database method missing: {e}")
        try:
            global db
            logger.info("Attempting to reinitialize database...")
            db = Database()
            jobs = db.get_all_active_jobs()
            logger.info(f"Reinitialized database - loaded {len(jobs)} jobs")
            return render_template('dashboard.html', jobs=jobs)
        except Exception as reinit_error:
            logger.error(f"Reinitialization failed: {reinit_error}")
            return f"""
            <h1>⚠️ Database Error</h1>
            <p><strong>Error:</strong> {str(e)}</p>
            <p>This usually means the database file is missing or corrupted.</p>
            <p><a href="/api/debug-db">Check Database Status</a></p>
            <p><small>Try running a new scan to recreate the database.</small></p>
            """, 500
            
    except sqlite3.OperationalError as e:
        # Database file issue
        logger.error(f"Database operational error: {e}")
        return f"""
        <h1>⚠️ Database Error</h1>
        <p><strong>Error:</strong> {str(e)}</p>
        <p>The database file may be corrupted or missing.</p>
        <p><a href="/api/debug-db">Check Database Status</a></p>
        """, 500
        
    except Exception as e:
        # Any other error
        logger.error(f"Dashboard error: {e}")
        error_details = traceback.format_exc()
        logger.error(error_details)
        return f"""
        <h1>⚠️ Dashboard Error</h1>
        <p><strong>Error:</strong> {str(e)}</p>
        <h3>Stack Trace:</h3>
        <pre style="background:#f4f4f4;padding:15px;border-radius:5px;overflow:auto;max-height:400px;">{error_details}</pre>
        <p><a href="/api/debug-db">Check Database</a> | <a href="/api/jobs">View Jobs API</a></p>
        """, 500

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
        
        if cv_matcher:
            matched_jobs = cv_matcher.filter_jobs_by_template_match(jobs, threshold=0.30)
            logger.info(f"Filtered to {len(matched_jobs)} matched jobs")
        else:
            matched_jobs = jobs
            logger.info("CV matcher disabled - processing all jobs")
        
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
    
    thread = threading.Thread(target=run_full_backfill)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'status': 'success',
        'message': 'Backfill started! It will run in 10-day batches over the last 60 days. Check logs for progress.'
    })

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
        
        if cv_matcher:
            matched_jobs = cv_matcher.filter_jobs_by_template_match(jobs, threshold=0.30)
            logger.info(f"Filtered to {len(matched_jobs)} matched jobs")
        else:
            matched_jobs = jobs
            logger.info("CV matcher disabled - processing all jobs")
        
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

@app.route('/api/jobs')
def get_jobs():
    """Get all active jobs as JSON"""
    if db:
        jobs = db.get_all_active_jobs()
    else:
        jobs = []
    return jsonify(jobs)

@app.route('/api/delete/<job_id>', methods=['POST'])
def delete_job(job_id):
    """Delete a job from the dashboard"""
    try:
        if db:
            success = db.delete_job(job_id)
            if success:
                return jsonify({'status': 'success', 'message': 'Job deleted successfully'})
        return jsonify({'status': 'error', 'message': 'Job not found'}), 404
    except Exception as e:
        logger.error(f"Delete error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/apply-now/<job_id>', methods=['POST'])
def mark_applied(job_id):
    """Mark a job as applied"""
    try:
        if db:
            success = db.mark_applied(job_id)
            if success:
                return jsonify({'status': 'success', 'message': 'Job marked as applied'})
        return jsonify({'status': 'error', 'message': 'Job not found'}), 404
    except Exception as e:
        logger.error(f"Mark applied error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/apply/<job_id>')
def apply_job(job_id):
    """Get application materials for a specific job"""
    try:
        logger.info(f"Fetching job with ID: {job_id}")
        if not db:
            return jsonify({'cv': 'Database not available', 'cover_letter': 'Database not available', 'answers': {}})
            
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
    """Save edited CV and cover letter"""
    try:
        data = request.get_json()
        cv_edited = data.get('cv', '')
        cover_letter_edited = data.get('cover_letter', '')
        
        logger.info(f"Saving edits for job: {job_id}")
        
        if not db:
            return jsonify({'status': 'error', 'message': 'Database not available'}), 500
            
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
    """Check if a scan is running"""
    return jsonify({'scan_running': scan_running})

@app.route('/api/templates')
def list_templates():
    """List all loaded JD templates"""
    if cv_matcher:
        return jsonify({'templates': cv_matcher.list_templates()})
    return jsonify({'templates': [], 'message': 'CV matcher disabled'})

@app.route('/api/debug-db')
def debug_db():
    """Debug endpoint to check database status"""
    try:
        if not db:
            return jsonify({
                'status': 'error',
                'message': 'Database not initialized',
                'db_path': 'data/jobs.db'
            }), 500
            
        # Check if file exists
        db_path = 'data/jobs.db'
        file_exists = os.path.exists(db_path)
        file_size = os.path.getsize(db_path) if file_exists else 0
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
        table_exists = cursor.fetchone() is not None
        
        if table_exists:
            cursor.execute("SELECT COUNT(*) FROM jobs WHERE deleted = 0")
            active_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM jobs")
            total_count = cursor.fetchone()[0]
            cursor.execute("SELECT job_id, title, company, match_score, cv_match_score, applied, created_at FROM jobs WHERE deleted = 0 ORDER BY created_at DESC LIMIT 10")
            rows = cursor.fetchall()
        else:
            active_count = 0
            total_count = 0
            rows = []
            
        conn.close()
        
        return jsonify({
            'status': 'success',
            'database': {
                'path': db_path,
                'exists': file_exists,
                'size_bytes': file_size,
                'table_exists': table_exists
            },
            'jobs': {
                'total': total_count,
                'active': active_count,
                'recent': [{'job_id': r[0], 'title': r[1], 'company': r[2], 'match_score': r[3], 'cv_match_score': r[4], 'applied': r[5], 'created_at': r[6]} for r in rows]
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e), 'traceback': traceback.format_exc()}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

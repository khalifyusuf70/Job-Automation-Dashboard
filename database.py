import os
import sqlite3
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path='data/jobs.db'):
        # Ensure the data directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()
        logger.info(f"Database initialized at {self.db_path}")

    def _init_db(self):
        """Initialize database tables"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    description TEXT,
                    match_score INTEGER,
                    assessment TEXT,
                    tailored_cv TEXT,
                    cover_letter TEXT,
                    answers TEXT,
                    url TEXT,
                    processed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
            conn.close()
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Database init error: {e}")

    def save_job(self, job_data):
        """Save or update a job"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO jobs (
                    job_id, title, company, description, match_score,
                    assessment, tailored_cv, cover_letter, answers,
                    url, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(job_data['job_id']),
                job_data['title'],
                job_data['company'],
                job_data['description'],
                job_data['match_score'],
                job_data['assessment'],
                job_data['tailored_cv'],
                job_data['cover_letter'],
                job_data['answers'],
                job_data['url'],
                job_data['processed_at']
            ))
            conn.commit()
            conn.close()
            logger.info(f"Saved job: {job_data['title']} at {job_data['company']}")
            return True
        except Exception as e:
            logger.error(f"Error saving job: {e}")
            return False

    def job_exists(self, job_id):
        """Check if job already exists"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM jobs WHERE job_id = ?', (str(job_id),))
            count = cursor.fetchone()[0]
            conn.close()
            return count > 0
        except Exception as e:
            logger.error(f"job_exists error: {e}")
            return False

    def get_todays_jobs(self):
        """Get jobs from today - with better date handling"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT * FROM jobs
                WHERE date(processed_at) = date(?)
                ORDER BY match_score DESC
            ''', (today,))
            columns = [description[0] for description in cursor.description]
            jobs = []
            for row in cursor.fetchall():
                job = dict(zip(columns, row))
                if job['answers']:
                    try:
                        job['answers'] = json.loads(job['answers'])
                    except:
                        job['answers'] = {}
                jobs.append(job)
            conn.close()
            logger.info(f"Found {len(jobs)} jobs for today ({today})")
            return jobs
        except Exception as e:
            logger.error(f"Error getting today's jobs: {e}")
            return []

    def get_job(self, job_id):
        """Get specific job by ID - FIXED with better error handling and fallback"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Try to find by job_id first, then by id (numeric)
            cursor.execute('SELECT * FROM jobs WHERE job_id = ? OR id = ?', (str(job_id), str(job_id)))
            columns = [description[0] for description in cursor.description]
            row = cursor.fetchone()
            conn.close()
            
            if row:
                job = dict(zip(columns, row))
                if job['answers']:
                    try:
                        job['answers'] = json.loads(job['answers'])
                    except:
                        job['answers'] = {}
                logger.info(f"Found job: {job.get('title')} with ID: {job.get('job_id')}")
                return job
            
            # If not found, try without the WHERE clause to debug
            logger.warning(f"Job not found: {job_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting job: {e}")
            return None

    def get_all_jobs(self, limit=50):
        """Get all jobs (for debugging)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT job_id, title, company, match_score FROM jobs ORDER BY created_at DESC LIMIT ?', (limit,))
            rows = cursor.fetchall()
            conn.close()
            return [{'job_id': r[0], 'title': r[1], 'company': r[2], 'match_score': r[3]} for r in rows]
        except Exception as e:
            logger.error(f"Error getting all jobs: {e}")
            return []

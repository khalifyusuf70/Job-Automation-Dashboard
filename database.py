import os
import sqlite3
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path='data/jobs.db'):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()
        logger.info(f"Database initialized at {self.db_path}")

    def _init_db(self):
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
                    cv_match_score REAL DEFAULT 0,
                    matched_template TEXT DEFAULT '',
                    assessment TEXT,
                    tailored_cv TEXT,
                    cover_letter TEXT,
                    answers TEXT,
                    url TEXT,
                    processed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    cv_edited TEXT DEFAULT '',
                    cover_letter_edited TEXT DEFAULT ''
                )
            ''')
            
            cursor.execute("PRAGMA table_info(jobs)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'cv_match_score' not in columns:
                cursor.execute("ALTER TABLE jobs ADD COLUMN cv_match_score REAL DEFAULT 0")
            if 'matched_template' not in columns:
                cursor.execute("ALTER TABLE jobs ADD COLUMN matched_template TEXT DEFAULT ''")
            if 'cv_edited' not in columns:
                cursor.execute("ALTER TABLE jobs ADD COLUMN cv_edited TEXT DEFAULT ''")
            if 'cover_letter_edited' not in columns:
                cursor.execute("ALTER TABLE jobs ADD COLUMN cover_letter_edited TEXT DEFAULT ''")
            
            conn.commit()
            conn.close()
            logger.info("Database tables created/updated successfully")
        except Exception as e:
            logger.error(f"Database init error: {e}")

    def save_job(self, job_data):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO jobs (
                    job_id, title, company, description, match_score,
                    cv_match_score, matched_template,
                    assessment, tailored_cv, cover_letter, answers,
                    url, processed_at, cv_edited, cover_letter_edited
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(job_data['job_id']),
                job_data['title'],
                job_data['company'],
                job_data['description'],
                job_data['match_score'],
                job_data.get('cv_match_score', 0),
                job_data.get('matched_template', ''),
                job_data['assessment'],
                job_data['tailored_cv'],
                job_data['cover_letter'],
                job_data['answers'],
                job_data['url'],
                job_data['processed_at'],
                job_data.get('cv_edited', ''),
                job_data.get('cover_letter_edited', '')
            ))
            conn.commit()
            conn.close()
            logger.info(f"Saved job: {job_data['title']} at {job_data['company']}")
            return True
        except Exception as e:
            logger.error(f"Error saving job: {e}")
            return False

    def job_exists(self, job_id):
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
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT * FROM jobs
                WHERE date(processed_at) = date(?)
                ORDER BY cv_match_score DESC, match_score DESC
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
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
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
                return job
            return None
        except Exception as e:
            logger.error(f"Error getting job: {e}")
            return None

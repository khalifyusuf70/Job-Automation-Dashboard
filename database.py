import sqlite3
import os
from datetime import datetime, timedelta
import json

class Database:
    def __init__(self, db_path='data/jobs.db'):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize database tables"""
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
    
    def save_job(self, job_data):
        """Save or update a job"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO jobs (
                job_id, title, company, description, match_score,
                assessment, tailored_cv, cover_letter, answers,
                url, processed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job_data['job_id'],
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
    
    def job_exists(self, job_id):
        """Check if job already exists"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM jobs WHERE job_id = ?', (job_id,))
        count = cursor.fetchone()[0]
        
        conn.close()
        return count > 0
    
    def get_todays_jobs(self):
        """Get jobs from today"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        today = datetime.now().date()
        cursor.execute('''
            SELECT * FROM jobs 
            WHERE date(processed_at) = date(?)
            ORDER BY match_score DESC
        ''', (today.isoformat(),))
        
        columns = [description[0] for description in cursor.description]
        jobs = []
        
        for row in cursor.fetchall():
            job = dict(zip(columns, row))
            if job['answers']:
                job['answers'] = json.loads(job['answers'])
            jobs.append(job)
        
        conn.close()
        return jobs
    
    def get_job(self, job_id):
        """Get specific job by ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM jobs WHERE job_id = ?', (job_id,))
        
        columns = [description[0] for description in cursor.description]
        row = cursor.fetchone()
        
        conn.close()
        
        if row:
            job = dict(zip(columns, row))
            if job['answers']:
                job['answers'] = json.loads(job['answers'])
            return job
        return None

import os
import requests
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)

class LinkedInScraper:
    def __init__(self):
        self.apify_token = os.getenv('APIFY_TOKEN')
        self.apify_actor_id = 'number_one_scraper~cheap-advance-linkedin-jobs-scraper'
        self.api_url = f"https://api.apify.com/v2/acts/{self.apify_actor_id}/runs"
        
    def scrape_last_24_hours(self, keyword='Software Engineer', location='Remote'):
        """Scrape jobs posted in the last 24 hours"""
        try:
            payload = {
                'keyword': [keyword],
                'location': location,
                'publishedAt': 'r86400',  # Last 24 hours
                'maxItems': 100,
                'country': 'US'
            }
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            # Start the scraper
            response = requests.post(
                f"{self.api_url}?token={self.apify_token}",
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            
            run_data = response.json()
            run_id = run_data['data']['id']
            
            # Wait for completion (you might want to implement polling)
            # For production, use webhook or implement proper polling
            import time
            time.sleep(10)  # Simple wait
            
            # Get results
            result_url = f"https://api.apify.com/v2/actor-runs/{run_id}/items?token={self.apify_token}"
            result_response = requests.get(result_url)
            result_response.raise_for_status()
            
            items = result_response.json()['items']
            
            # Format jobs
            jobs = []
            for item in items:
                jobs.append({
                    'id': item.get('id', f"job_{len(jobs)}"),
                    'title': item.get('title', 'Unknown Position'),
                    'company': item.get('company', {}).get('name', 'Unknown Company'),
                    'description': item.get('description', ''),
                    'url': item.get('url', ''),
                    'posted_at': item.get('postedAt', datetime.now().isoformat()),
                    'location': item.get('location', ''),
                    'salary': item.get('salary', ''),
                    'skills': item.get('skills', [])
                })
            
            return jobs
            
        except Exception as e:
            logger.error(f"Scraping error: {e}")
            # Return fallback data for testing
            return self._get_fallback_jobs()
    
    def _get_fallback_jobs(self):
        """Return example jobs if scraper fails (for testing)"""
        return [
            {
                'id': 'job_1',
                'title': 'Senior Software Engineer',
                'company': 'Tech Corp',
                'description': 'Looking for experienced Python developer...',
                'url': 'https://linkedin.com/jobs/1',
                'posted_at': datetime.now().isoformat(),
                'location': 'Remote',
                'skills': ['Python', 'Django', 'AWS']
            },
            {
                'id': 'job_2',
                'title': 'Full Stack Developer',
                'company': 'Startup Inc',
                'description': 'React and Node.js expert needed...',
                'url': 'https://linkedin.com/jobs/2',
                'posted_at': datetime.now().isoformat(),
                'location': 'Remote',
                'skills': ['React', 'Node.js', 'MongoDB']
            }
        ]

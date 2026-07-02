import os
import requests
from datetime import datetime
import logging
import time
import json

logger = logging.getLogger(__name__)

class LinkedInScraper:
    def __init__(self):
        self.apify_token = os.getenv('APIFY_TOKEN')
        self.apify_actor_id = 'number_one_scraper~cheap-advance-linkedin-jobs-scraper'
        self.api_url = f"https://api.apify.com/v2/acts/{self.apify_actor_id}"
        self.locations = ['Kenya']
        self.max_daily_jobs = 200
        
        # Use only 3 most common senior keywords
        self.senior_keywords = [
            'manager', 'senior', 'director'
        ]
        
    def scrape_last_24_hours(self, keyword=None, location=None):
        all_jobs = []
        if location:
            return self._scrape_location(location)

        total_fetched = 0
        
        for loc in self.locations:
            if total_fetched >= self.max_daily_jobs:
                logger.info(f"Reached daily limit of {self.max_daily_jobs} jobs")
                break
                
            try:
                logger.info(f"Scraping senior jobs in: {loc}")
                jobs = self._scrape_location(loc, total_fetched)
                
                remaining = self.max_daily_jobs - total_fetched
                if len(jobs) > remaining:
                    jobs = jobs[:remaining]
                    
                total_fetched += len(jobs)
                all_jobs.extend(jobs)
                logger.info(f"Found {len(jobs)} jobs in {loc} (total: {total_fetched}/{self.max_daily_jobs})")
                time.sleep(1)
            except Exception as e:
                logger.error(f"Error scraping {loc}: {e}")
                continue

        seen_urls = set()
        unique_jobs = []
        for job in all_jobs:
            if job['url'] not in seen_urls:
                seen_urls.add(job['url'])
                unique_jobs.append(job)

        filtered = self._filter_entry_level_only(unique_jobs)
        logger.info(f"SUMMARY - Total: {len(all_jobs)}, After dedupe: {len(unique_jobs)}, After filtering: {len(filtered)}")
        return filtered

    def _scrape_location(self, location, current_total=0):
        """
        Scrape a location with a SHORT timeout - returns what it can
        """
        try:
            remaining_daily = self.max_daily_jobs - current_total
            if remaining_daily <= 0:
                return []
                
            items_to_fetch = min(50, remaining_daily)  # Reduce to 50
            
            payload = {
                'keyword': self.senior_keywords,
                'location': location,
                'publishedAt': 'r86400',
                'maxItems': items_to_fetch,
                'saveOnlyUniqueItems': True,
                'cleanDescription': False,
                'enrichCompanyData': False
            }
            
            if location.lower() == 'kenya':
                payload['country'] = 'KE'

            logger.info(f"Searching in {location} with: {self.senior_keywords}")
            logger.info(f"Max items: {items_to_fetch}")

            headers = {'Content-Type': 'application/json'}
            
            # Use run-sync with SHORT timeout (20 seconds)
            sync_url = f"{self.api_url}/run-sync-get-dataset-items?token={self.apify_token}&timeout=20"
            
            response = requests.post(
                sync_url,
                json=payload,
                headers=headers,
                timeout=25  # 25 second total timeout
            )
            
            if response.status_code in [408, 504, 502]:
                logger.warning(f"Timeout for {location} - returning partial results")
                return []
                
            if response.status_code == 404:
                logger.warning(f"No results found for {location}")
                return []
                
            response.raise_for_status()
            items = response.json()
            
            if not items:
                logger.warning(f"No items returned for {location}")
                return []
            
            jobs = []
            for item in items:
                jobs.append({
                    'id': item.get('id', f"job_{len(jobs)}"),
                    'title': item.get('jobTitle', item.get('title', 'Unknown Position')),
                    'company': item.get('companyName', item.get('company', {}).get('name', 'Unknown Company')),
                    'description': item.get('description', item.get('jobDescription', '')),
                    'url': item.get('jobUrl', item.get('url', '')),
                    'posted_at': item.get('postedTime', item.get('postedAt', datetime.now().isoformat())),
                    'location': item.get('location', location),
                    'salary': item.get('salaryInfo', item.get('salary', 'Not specified')),
                    'skills': item.get('skills', []),
                    'experience_level': item.get('experienceLevel', 'Not specified'),
                    'job_type': item.get('contractType', item.get('employmentType', 'Not specified')),
                    'work_type': item.get('workType', 'Not specified')
                })
                
            logger.info(f"Retrieved {len(jobs)} jobs from {location}")
            return jobs
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout scraping {location}")
            return []
        except Exception as e:
            logger.error(f"Scraping error for {location}: {e}")
            return []

    def _filter_entry_level_only(self, jobs):
        """Remove ONLY entry-level jobs"""
        entry_level_keywords = [
            'junior', 'entry', 'entry level', 'entry-level',
            'intern', 'internship', 'trainee', 'fresher',
            'graduate', 'graduate trainee', 'apprentice'
        ]
        
        filtered = []
        for job in jobs:
            title_lower = job['title'].lower()
            
            is_entry = any(k in title_lower for k in entry_level_keywords)
            if is_entry:
                senior_indicators = ['senior', 'lead', 'principal', 'manager', 'director', 'executive']
                if any(ind in title_lower for ind in senior_indicators):
                    filtered.append(job)
                continue

            filtered.append(job)
            
        return filtered

    def _get_fallback_jobs(self):
        return [
            {
                'id': 'job_1',
                'title': 'Senior Manager',
                'company': 'Major Corp',
                'description': 'Looking for experienced Manager...',
                'url': 'https://linkedin.com/jobs/1',
                'posted_at': datetime.now().isoformat(),
                'location': 'Nairobi, Kenya',
                'salary': 'Competitive',
                'skills': ['Leadership', 'Strategy'],
                'experience_level': 'Mid-Senior',
                'job_type': 'Full-time',
                'work_type': 'On-site'
            }
        ]

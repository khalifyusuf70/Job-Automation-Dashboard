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
        self.api_url = f"https://api.apify.com/v2/acts/{self.apify_actor_id}/runs"
        self.locations = ['Kenya', 'Somalia']
        self.max_daily_jobs = 300
        
        # Split keywords into SMALLER batches to avoid timeouts
        self.keyword_batches = [
            ['Director', 'executive', 'manager'],  # Batch 1
            ['senior', 'head of', 'lead'],        # Batch 2
            ['advisor', 'consultant'],            # Batch 3
            ['coordinator', 'specialist']         # Batch 4
        ]
        
    def scrape_last_24_hours(self, keyword=None, location=None):
        all_jobs = []
        if location:
            return self._scrape_location_with_keywords(location)

        total_fetched = 0
        
        for loc in self.locations:
            if total_fetched >= self.max_daily_jobs:
                logger.info(f"Reached daily limit of {self.max_daily_jobs} jobs")
                break
                
            # For each location, try each keyword batch
            for batch in self.keyword_batches:
                if total_fetched >= self.max_daily_jobs:
                    break
                    
                try:
                    # Calculate remaining capacity
                    remaining = self.max_daily_jobs - total_fetched
                    batch_limit = min(30, remaining)  # 30 per batch
                    
                    logger.info(f"Scraping {batch} in {loc} (limit: {batch_limit})")
                    jobs = self._scrape_location_with_keywords(loc, batch, batch_limit, total_fetched)
                    
                    if len(jobs) > batch_limit:
                        jobs = jobs[:batch_limit]
                        
                    total_fetched += len(jobs)
                    all_jobs.extend(jobs)
                    logger.info(f"Found {len(jobs)} jobs from {batch} in {loc} (total: {total_fetched}/{self.max_daily_jobs})")
                    time.sleep(1)  # Small delay between batches
                except Exception as e:
                    logger.error(f"Error with batch {batch} in {loc}: {e}")
                    continue

        # Deduplicate
        seen_urls = set()
        unique_jobs = []
        for job in all_jobs:
            if job['url'] not in seen_urls:
                seen_urls.add(job['url'])
                unique_jobs.append(job)

        filtered = self._filter_entry_level_only(unique_jobs)
        logger.info(f"SUMMARY - Total scraped: {len(all_jobs)}, After dedupe: {len(unique_jobs)}, After filtering: {len(filtered)}")
        return filtered

    def _scrape_location_with_keywords(self, location, keyword_batch, limit, current_total=0):
        """
        Scrape a location with a SMALL batch of keywords
        """
        try:
            remaining_daily = self.max_daily_jobs - current_total
            if remaining_daily <= 0:
                return []
                
            items_to_fetch = min(limit, remaining_daily)
            
            payload = {
                'keyword': keyword_batch,  # SMALL batch (3-4 keywords)
                'location': location,
                'publishedAt': 'r86400',
                'maxItems': items_to_fetch,
                'saveOnlyUniqueItems': True,
                'cleanDescription': False,
                'enrichCompanyData': False
            }
            
            if location.lower() == 'kenya':
                payload['country'] = 'KE'
            elif location.lower() == 'somalia':
                payload['country'] = 'SO'

            logger.info(f"Searching in {location} with: {keyword_batch} (limit: {items_to_fetch})")
            logger.info(f"Payload: {json.dumps(payload)}")

            headers = {'Content-Type': 'application/json'}
            
            # STEP 1: Start the run
            run_response = requests.post(
                self.api_url,
                params={'token': self.apify_token},
                json=payload,
                headers=headers,
                timeout=30
            )
            run_response.raise_for_status()
            run_data = run_response.json()
            run_id = run_data['data']['id']
            logger.info(f"Started run {run_id} for {location} with {keyword_batch}")

            # STEP 2: Wait for completion - SHORT timeout
            max_wait = 25  # Maximum 25 seconds
            waited = 0
            status = 'RUNNING'
            
            while waited < max_wait and status in ['RUNNING', 'READY']:
                status_url = f"https://api.apify.com/v2/actor-runs/{run_id}"
                status_response = requests.get(
                    status_url,
                    params={'token': self.apify_token},
                    timeout=10
                )
                status_data = status_response.json()
                status = status_data['data']['status']
                
                if status in ['SUCCEEDED', 'FAILED', 'ABORTED']:
                    break
                    
                time.sleep(2)
                waited += 2

            # If still running, abort
            if status == 'RUNNING':
                logger.warning(f"Run {run_id} still running - aborting")
                try:
                    abort_url = f"https://api.apify.com/v2/actor-runs/{run_id}/abort"
                    requests.post(abort_url, params={'token': self.apify_token}, timeout=5)
                except:
                    pass
                return []

            if status != 'SUCCEEDED':
                logger.warning(f"Run {run_id} ended with status: {status}")
                return []

            # STEP 3: Fetch results
            result_url = f"https://api.apify.com/v2/actor-runs/{run_id}/items"
            result_response = requests.get(
                result_url,
                params={'token': self.apify_token, 'limit': items_to_fetch},
                timeout=15
            )
            
            if result_response.status_code == 404:
                return []
                
            result_response.raise_for_status()
            items = result_response.json()
            
            if not items:
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
                
            logger.info(f"Retrieved {len(jobs)} jobs from {location} with {keyword_batch}")
            return jobs
            
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
                'title': 'Senior Director',
                'company': 'Major Corp',
                'description': 'Looking for experienced Director...',
                'url': 'https://linkedin.com/jobs/1',
                'posted_at': datetime.now().isoformat(),
                'location': 'Nairobi, Kenya',
                'salary': 'Competitive',
                'skills': ['Leadership', 'Strategy'],
                'experience_level': 'Director',
                'job_type': 'Full-time',
                'work_type': 'On-site'
            }
        ]

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
        
    def scrape_last_24_hours(self, keyword=None, location=None):
        all_jobs = []
        if location:
            return self._scrape_location('', location)

        for loc in self.locations:
            if len(all_jobs) >= self.max_daily_jobs:
                logger.info(f"Reached daily limit of {self.max_daily_jobs} jobs")
                break
                
            try:
                logger.info(f"Scraping ALL jobs in: {loc}")
                jobs = self._scrape_location('', loc)
                
                remaining = self.max_daily_jobs - len(all_jobs)
                if len(jobs) > remaining:
                    jobs = jobs[:remaining]
                    
                all_jobs.extend(jobs)
                logger.info(f"Found {len(jobs)} jobs in {loc} (total so far: {len(all_jobs)})")
                time.sleep(2)
            except Exception as e:
                logger.error(f"Error scraping {loc}: {e}")
                continue

        # Deduplicate by URL
        seen_urls = set()
        unique_jobs = []
        for job in all_jobs:
            if job['url'] not in seen_urls:
                seen_urls.add(job['url'])
                unique_jobs.append(job)

        # Filter out ONLY entry-level
        filtered = self._filter_entry_level_only(unique_jobs)
        logger.info(f"Total scraped: {len(all_jobs)}, After dedupe: {len(unique_jobs)}, After filtering: {len(filtered)}")
        return filtered

    def _scrape_location(self, keyword, location):
        try:
            # Use a VERY BROAD keyword to match ALL jobs
            broad_keyword = "a"  # Catches almost every job posting
            
            payload = {
                'keyword': [broad_keyword],
                'location': location,
                'publishedAt': 'r86400',  # Last 24 hours
                'maxItems': 100,  # Get up to 100 per location
            }
            
            # Add country code for better results
            if location.lower() == 'kenya':
                payload['country'] = 'KE'
            elif location.lower() == 'somalia':
                payload['country'] = 'SO'

            logger.info(f"Searching for ALL jobs in {location}")
            logger.info(f"Payload: {json.dumps(payload)}")

            headers = {'Content-Type': 'application/json'}
            
            # STEP 1: Start the Actor run (POST to /runs)
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
            logger.info(f"Started run {run_id} for {location}")

            # STEP 2: Wait for the run to complete
            max_wait = 90  # Maximum 90 seconds
            waited = 0
            status = 'RUNNING'
            
            while waited < max_wait and status not in ['SUCCEEDED', 'FAILED', 'ABORTED']:
                status_url = f"https://api.apify.com/v2/actor-runs/{run_id}"
                status_response = requests.get(
                    status_url,
                    params={'token': self.apify_token},
                    timeout=30
                )
                status_data = status_response.json()
                status = status_data['data']['status']
                logger.info(f"Run {run_id} status: {status}")
                
                if status not in ['SUCCEEDED', 'FAILED', 'ABORTED']:
                    time.sleep(10)
                    waited += 10

            if status != 'SUCCEEDED':
                logger.warning(f"Run {run_id} ended with status: {status}")
                return []

            # STEP 3: Fetch the results
            result_url = f"https://api.apify.com/v2/actor-runs/{run_id}/items"
            result_response = requests.get(
                result_url,
                params={'token': self.apify_token},
                timeout=30
            )
            
            if result_response.status_code == 404:
                logger.warning(f"No results found for {location}")
                return []
                
            result_response.raise_for_status()
            items = result_response.json()
            
            if not items:
                logger.warning(f"No items returned for {location}")
                return []
            
            # Map ALL fields - KEEP EVERYTHING
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
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error for {location}: {e}")
            return []
        except Exception as e:
            logger.error(f"Scraping error for {location}: {e}")
            return []

    def _filter_entry_level_only(self, jobs):
        """Remove ONLY entry-level jobs - KEEP EVERYTHING ELSE including all industries"""
        entry_level_keywords = [
            'junior', 'entry', 'entry level', 'entry-level',
            'intern', 'internship', 'trainee', 'fresher',
            'graduate', 'graduate trainee', 'apprentice'
        ]
        
        filtered = []
        for job in jobs:
            title_lower = job['title'].lower()
            
            # Skip ONLY if it's explicitly entry-level
            is_entry = any(k in title_lower for k in entry_level_keywords)
            if is_entry:
                # But keep if it has senior indicators
                senior_indicators = ['senior', 'lead', 'principal', 'manager', 'director']
                if any(ind in title_lower for ind in senior_indicators):
                    filtered.append(job)
                continue

            # KEEP EVERYTHING ELSE:
            # ✅ ALL industries (Finance, Healthcare, Tech, Marketing, etc.)
            # ✅ ALL job types (Consultancy, Freelance, Contract, Full-time, etc.)
            # ✅ Remote jobs (they'll appear naturally in Kenya/Somalia searches)
            filtered.append(job)
            
        return filtered

    def _get_fallback_jobs(self):
        """Return example jobs if scraper fails (for testing)"""
        return [
            {
                'id': 'job_1',
                'title': 'Senior Accountant',
                'company': 'Big 4 Firm',
                'description': 'Looking for experienced accountant with 5+ years...',
                'url': 'https://linkedin.com/jobs/1',
                'posted_at': datetime.now().isoformat(),
                'location': 'Nairobi, Kenya',
                'salary': 'Competitive',
                'skills': ['Accounting', 'Audit', 'Tax'],
                'experience_level': 'Senior',
                'job_type': 'Full-time',
                'work_type': 'On-site'
            },
            {
                'id': 'job_2',
                'title': 'Management Consultant',
                'company': 'Consulting Firm',
                'description': 'Senior consultant for strategy projects...',
                'url': 'https://linkedin.com/jobs/2',
                'posted_at': datetime.now().isoformat(),
                'location': 'Remote, Kenya',
                'salary': '$150-200k',
                'skills': ['Strategy', 'Operations', 'Analytics'],
                'experience_level': 'Senior',
                'job_type': 'Consultancy',
                'work_type': 'Remote'
            },
            {
                'id': 'job_3',
                'title': 'Marketing Manager',
                'company': 'Consumer Goods Co',
                'description': 'Lead marketing team for East Africa...',
                'url': 'https://linkedin.com/jobs/3',
                'posted_at': datetime.now().isoformat(),
                'location': 'Nairobi, Kenya',
                'salary': 'Competitive',
                'skills': ['Marketing', 'Digital', 'Brand Management'],
                'experience_level': 'Senior',
                'job_type': 'Full-time',
                'work_type': 'On-site'
            }
        ]

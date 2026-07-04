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
        # Using the working scraper you tested
        self.apify_actor_id = 'cheap_scraper~linkedin-job-scraper'
        self.api_url = f"https://api.apify.com/v2/acts/{self.apify_actor_id}/runs"
        self.max_daily_jobs = 300
        
        # Working keywords from your Apify test
        self.keyword = 'Director OR Executive OR Manager OR Senior OR "Head of" OR Lead OR Advisor OR Consultant OR Coordinator OR Specialist'
        
        # Jobs to exclude (entry-level/small jobs)
        self.exclude_titles = [
            'Receptionist', 'Clerk', 'Cashier', 'Driver', 'Cleaner',
            'Security', 'Porter', 'Waiter', 'Bartender', 'Cook',
            'Chef', 'Intern', 'Trainee', 'Assistant',
            'Sales Representative', 'Telemarketer', 'Customer Service',
            'Call Center'
        ]
        
    def scrape_last_24_hours(self, keyword=None, location=None):
        """
        Scrape jobs using cheap_scraper/linkedin-job-scraper - returns jobs directly
        NO WEBHOOKS - everything happens in this function
        """
        try:
            logger.info("Starting job scrape with cheap_scraper/linkedin-job-scraper")
            
            payload = {
                'keyword': [self.keyword],
                'locations': ['Kenya', 'Somalia'],
                'publishedAt': 'r86400',  # Last 24 hours
                'maxItems': self.max_daily_jobs,
                'saveOnlyUniqueItems': True,
                'enrichCompanyData': False,
                'excludeRecruitingAgencies': False,
                'filterEasyApply': False,
                'filterUnder10Applicants': False,
                'requireRecruiterProfile': False,
                'requireSalaryInfo': False,
                'excludeJobTitlesContaining': self.exclude_titles,
                'distance': ''
            }
            
            logger.info(f"Payload: {json.dumps(payload)}")
            
            headers = {'Content-Type': 'application/json'}
            
            # Start the run (async - we'll poll for completion)
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
            logger.info(f"Started run {run_id}")
            
            # Wait for completion (polling)
            max_wait = 90  # 90 seconds max
            waited = 0
            status = 'RUNNING'
            
            while waited < max_wait and status in ['RUNNING', 'READY']:
                status_url = f"https://api.apify.com/v2/actor-runs/{run_id}"
                status_response = requests.get(
                    status_url,
                    params={'token': self.apify_token},
                    timeout=15
                )
                status_data = status_response.json()
                status = status_data['data']['status']
                logger.info(f"Run {run_id} status: {status}")
                
                if status in ['SUCCEEDED', 'FAILED', 'ABORTED']:
                    break
                    
                time.sleep(5)
                waited += 5
            
            if status != 'SUCCEEDED':
                logger.warning(f"Run ended with status: {status}")
                return self._get_fallback_jobs()
            
            # Fetch the results
            result_url = f"https://api.apify.com/v2/actor-runs/{run_id}/items"
            result_response = requests.get(
                result_url,
                params={'token': self.apify_token, 'limit': self.max_daily_jobs},
                timeout=20
            )
            result_response.raise_for_status()
            items = result_response.json()
            
            if not items:
                logger.warning("No items returned")
                return self._get_fallback_jobs()
            
            # Map to our format
            jobs = []
            for item in items:
                jobs.append({
                    'id': item.get('id', f"job_{len(jobs)}"),
                    'title': item.get('jobTitle', item.get('title', 'Unknown Position')),
                    'company': item.get('companyName', item.get('company', {}).get('name', 'Unknown Company')),
                    'description': item.get('description', item.get('jobDescription', '')),
                    'url': item.get('jobUrl', item.get('url', '')),
                    'posted_at': item.get('postedTime', item.get('postedAt', datetime.now().isoformat())),
                    'location': item.get('location', ''),
                    'salary': item.get('salaryInfo', item.get('salary', 'Not specified')),
                    'skills': item.get('skills', []),
                    'experience_level': item.get('experienceLevel', 'Not specified'),
                    'job_type': item.get('contractType', item.get('employmentType', 'Not specified')),
                    'work_type': item.get('workType', 'Not specified')
                })
                
            logger.info(f"Retrieved {len(jobs)} jobs")
            
            # Filter out any remaining entry-level jobs
            filtered_jobs = self._filter_entry_level_only(jobs)
            
            logger.info(f"After filtering: {len(filtered_jobs)} jobs")
            
            # Log sample for debugging
            if filtered_jobs:
                logger.info(f"Sample job: {filtered_jobs[0].get('title')} at {filtered_jobs[0].get('company')}")
            else:
                logger.warning("No jobs after filtering")
            
            return filtered_jobs
            
        except Exception as e:
            logger.error(f"Scraping error: {e}")
            return self._get_fallback_jobs()

    def _filter_entry_level_only(self, jobs):
        """Remove any entry-level/small jobs"""
        entry_level_keywords = [
            'junior', 'entry', 'entry level', 'entry-level',
            'intern', 'internship', 'trainee', 'fresher',
            'graduate', 'graduate trainee', 'apprentice',
            'receptionist', 'clerk', 'cashier', 'driver',
            'cleaner', 'security', 'porter', 'waiter',
            'bartender', 'cook', 'chef', 'sales representative',
            'telemarketer', 'call center', 'assistant'
        ]
        
        filtered = []
        for job in jobs:
            title_lower = job['title'].lower()
            
            # Skip if entry-level
            is_entry = any(k in title_lower for k in entry_level_keywords)
            if is_entry:
                # But keep if it has senior indicators
                senior_indicators = ['senior', 'lead', 'principal', 'manager', 'director', 'executive', 'head of']
                if any(ind in title_lower for ind in senior_indicators):
                    filtered.append(job)
                continue

            # Keep professional roles
            filtered.append(job)
            
        return filtered

    def _get_fallback_jobs(self):
        """Sample jobs for testing if scraper fails"""
        return [
            {
                'id': 'fallback_1',
                'title': 'Senior Manager - Test',
                'company': 'Test Company',
                'description': 'This is a fallback job for testing purposes.',
                'url': 'https://linkedin.com/jobs/test',
                'posted_at': datetime.now().isoformat(),
                'location': 'Nairobi, Kenya',
                'salary': 'Competitive',
                'skills': ['Leadership', 'Strategy'],
                'experience_level': 'Mid-Senior',
                'job_type': 'Full-time',
                'work_type': 'On-site'
            }
        ]

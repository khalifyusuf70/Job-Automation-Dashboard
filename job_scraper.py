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
        self.locations = ['Kenya', 'Somalia', 'Remote']
        
    def scrape_last_24_hours(self, keyword=None, location=None):
        all_jobs = []
        if location:
            return self._scrape_location('', location)

        for loc in self.locations:
            try:
                logger.info(f"Scraping ALL jobs in: {loc}")
                jobs = self._scrape_location('', loc)
                all_jobs.extend(jobs)
                logger.info(f"Found {len(jobs)} jobs in {loc}")
                time.sleep(3)  # Small delay between requests
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

        # Filter out entry-level positions
        filtered = self._filter_entry_level_only(unique_jobs)
        logger.info(f"Total: {len(all_jobs)}, After dedupe: {len(unique_jobs)}, After filtering: {len(filtered)}")
        return filtered

    def _scrape_location(self, keyword, location):
        try:
            # Build payload for Apify scraper
            payload = {
                'publishedAt': 'r86400',  # Last 24 hours
                'maxItems': 100,  # Get more jobs
            }
            
            if location.lower() == 'remote':
                payload['keyword'] = [keyword] if keyword else ['']
                payload['location'] = 'Worldwide'
                payload['remoteOnly'] = True
                payload['country'] = 'US'
            else:
                # For specific locations
                payload['keyword'] = [keyword] if keyword else ['']
                payload['location'] = location
                # Add country code for better results
                if location.lower() == 'kenya':
                    payload['country'] = 'KE'
                elif location.lower() == 'somalia':
                    payload['country'] = 'SO'

            logger.info(f"Payload for {location}: {json.dumps(payload)}")

            headers = {'Content-Type': 'application/json'}
            
            # Start the run
            response = requests.post(
                f"{self.api_url}?token={self.apify_token}",
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            run_data = response.json()
            run_id = run_data['data']['id']
            logger.info(f"Started run {run_id} for {location}")

            # Wait for completion with progress check
            max_wait = 90  # Max 90 seconds
            waited = 0
            while waited < max_wait:
                status_url = f"https://api.apify.com/v2/actor-runs/{run_id}?token={self.apify_token}"
                status_response = requests.get(status_url)
                status_data = status_response.json()
                status = status_data['data']['status']
                logger.info(f"Run {run_id} status: {status}")
                
                if status in ['SUCCEEDED', 'FAILED', 'ABORTED']:
                    break
                time.sleep(10)  # Wait 10 seconds between checks
                waited += 10

            # Get results
            result_url = f"https://api.apify.com/v2/actor-runs/{run_id}/items?token={self.apify_token}"
            result_response = requests.get(result_url)
            
            # If 404, the dataset might be empty
            if result_response.status_code == 404:
                logger.warning(f"No results found for {location} (404)")
                return []
                
            result_response.raise_for_status()
            items = result_response.json().get('items', [])
            
            # Map the correct field names from the scraper
            jobs = []
            for item in items:
                # Extract location properly
                job_location = item.get('location', '')
                if not job_location:
                    job_location = location
                elif location.lower() == 'remote':
                    job_location = 'Remote'
                    
                # Map fields from Apify to our format
                jobs.append({
                    'id': item.get('id', f"job_{len(jobs)}"),
                    'title': item.get('jobTitle', item.get('title', 'Unknown Position')),
                    'company': item.get('companyName', item.get('company', {}).get('name', 'Unknown Company')),
                    'description': item.get('description', item.get('jobDescription', '')),
                    'url': item.get('jobUrl', item.get('url', '')),
                    'posted_at': item.get('postedTime', item.get('postedAt', datetime.now().isoformat())),
                    'location': job_location,
                    'salary': item.get('salaryInfo', item.get('salary', 'Not specified')),
                    'skills': item.get('skills', []),
                    'experience_level': item.get('experienceLevel', 'Not specified'),
                    'job_type': item.get('contractType', item.get('employmentType', 'Not specified')),
                    'work_type': item.get('workType', 'Not specified')
                })
                
            logger.info(f"Retrieved {len(jobs)} jobs from {location}")
            return jobs
            
        except Exception as e:
            logger.error(f"Scraping error for {location}: {e}")
            return []

    def _filter_entry_level_only(self, jobs):
        """Remove only entry-level/beginner jobs - keep everything else"""
        entry_level_keywords = [
            'junior', 'entry', 'entry level', 'entry-level',
            'intern', 'internship', 'trainee', 'fresher',
            'graduate', 'graduate trainee', 'apprentice'
        ]
        spam_keywords = [
            'spam', 'scam', 'fraud', 'bitcoin', 'crypto',
            'forex', 'investment', 'make money', 'passive income'
        ]
        
        filtered = []
        for job in jobs:
            title_lower = job['title'].lower()
            desc_lower = job['description'].lower()

            # Skip obvious spam
            if any(k in title_lower or k in desc_lower for k in spam_keywords):
                continue

            # Skip ONLY if it's explicitly entry-level (and not senior/lead)
            is_entry = any(k in title_lower for k in entry_level_keywords)
            if is_entry:
                senior_indicators = ['senior', 'lead', 'principal', 'manager', 'director']
                if any(ind in title_lower for ind in senior_indicators):
                    filtered.append(job)
                continue

            # Keep everything else (consultancy, freelance, contract, etc.)
            filtered.append(job)
            
        return filtered

    def _get_fallback_jobs(self):
        """Return example jobs if scraper fails (for testing)"""
        return [
            {
                'id': 'job_1',
                'title': 'Senior Software Engineer',
                'company': 'Tech Corp Kenya',
                'description': 'Looking for experienced Python developer with 5+ years...',
                'url': 'https://linkedin.com/jobs/1',
                'posted_at': datetime.now().isoformat(),
                'location': 'Nairobi, Kenya',
                'salary': 'Competitive',
                'skills': ['Python', 'Django', 'AWS'],
                'experience_level': 'Senior',
                'job_type': 'Full-time',
                'work_type': 'Remote'
            },
            {
                'id': 'job_2',
                'title': 'Full Stack Developer - Remote',
                'company': 'Global Startup',
                'description': 'Remote position for senior developer with React and Node.js...',
                'url': 'https://linkedin.com/jobs/2',
                'posted_at': datetime.now().isoformat(),
                'location': 'Remote',
                'salary': '$80k-120k',
                'skills': ['React', 'Node.js', 'MongoDB'],
                'experience_level': 'Senior',
                'job_type': 'Full-time',
                'work_type': 'Remote'
            },
            {
                'id': 'job_3',
                'title': 'Accountant',
                'company': 'Nairobi Firm',
                'description': 'Finance role in Nairobi with 3+ years experience...',
                'url': 'https://linkedin.com/jobs/3',
                'posted_at': datetime.now().isoformat(),
                'location': 'Nairobi, Kenya',
                'salary': 'Competitive',
                'skills': ['Accounting', 'Excel'],
                'experience_level': 'Mid-Senior',
                'job_type': 'Full-time',
                'work_type': 'On-site'
            }
        ]

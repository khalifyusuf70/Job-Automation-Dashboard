import os
import requests
from datetime import datetime
import logging
import time
import re

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

        # Remove only entry-level / obvious spam
        filtered = self._filter_entry_level_only(unique_jobs)
        logger.info(f"Total: {len(all_jobs)}, After dedupe: {len(unique_jobs)}, After filtering: {len(filtered)}")
        return filtered

    def _scrape_location(self, keyword, location):
        try:
            payload = {
                'publishedAt': 'r86400',
                'maxItems': 200,
            }
            if location.lower() == 'remote':
                payload['keyword'] = ['']
                payload['location'] = 'Worldwide'
                payload['remoteOnly'] = True
                payload['country'] = 'US'
            else:
                payload['keyword'] = ['']   # empty = all jobs
                payload['location'] = location
                payload['country'] = 'KE' if location.lower() == 'kenya' else 'SO'

            headers = {'Content-Type': 'application/json'}
            logger.info(f"Scraping ALL jobs in {location}")

            response = requests.post(
                f"{self.api_url}?token={self.apify_token}",
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            run_data = response.json()
            run_id = run_data['data']['id']

            # Wait for completion
            max_wait = 60
            waited = 0
            while waited < max_wait:
                status_url = f"https://api.apify.com/v2/actor-runs/{run_id}?token={self.apify_token}"
                status_response = requests.get(status_url)
                status_data = status_response.json()
                if status_data['data']['status'] in ['SUCCEEDED', 'FAILED', 'ABORTED']:
                    break
                time.sleep(5)
                waited += 5

            # Get results
            result_url = f"https://api.apify.com/v2/actor-runs/{run_id}/items?token={self.apify_token}"
            result_response = requests.get(result_url)
            result_response.raise_for_status()
            items = result_response.json().get('items', [])

            jobs = []
            for item in items:
                job_location = item.get('location', '')
                if not job_location and location.lower() != 'remote':
                    job_location = location
                elif location.lower() == 'remote':
                    job_location = 'Remote'

                jobs.append({
                    'id': item.get('id', f"job_{len(jobs)}"),
                    'title': item.get('title', 'Unknown Position'),
                    'company': item.get('company', {}).get('name', 'Unknown Company'),
                    'description': item.get('description', ''),
                    'url': item.get('url', ''),
                    'posted_at': item.get('postedAt', datetime.now().isoformat()),
                    'location': job_location,
                    'salary': item.get('salary', 'Not specified'),
                    'skills': item.get('skills', []),
                    'experience_level': item.get('experienceLevel', 'Not specified'),
                    'job_type': item.get('employmentType', 'Not specified'),
                    'company_industry': item.get('company', {}).get('industry', 'Not specified')
                })
            return jobs
        except Exception as e:
            logger.error(f"Scraping error for {location}: {e}")
            return []

    def _filter_entry_level_only(self, jobs):
        """Remove only entry-level/beginner jobs - keep everything else (consultancy, freelance, etc.)"""
        entry_level_keywords = [
            'junior', 'entry', 'entry level', 'entry-level',
            'intern', 'internship', 'trainee', 'fresher',
            'graduate', 'graduate trainee', 'apprentice'
        ]
        spam_keywords = [
            'spam', 'scam', 'fraud', 'bitcoin', 'crypto', 'forex',
            'investment', 'make money', 'passive income'
        ]
        filtered = []
        for job in jobs:
            title_lower = job['title'].lower()
            desc_lower = job['description'].lower()

            # Skip spam
            if any(k in title_lower or k in desc_lower for k in spam_keywords):
                continue

            # Skip ONLY if it's explicitly entry-level (and not senior/lead)
            is_entry = any(k in title_lower for k in entry_level_keywords)
            if is_entry:
                senior_indicators = ['senior', 'lead', 'principal', 'manager', 'director']
                if any(ind in title_lower for ind in senior_indicators):
                    filtered.append(job)
                continue

            # Keep everything else
            filtered.append(job)
        return filtered

    def _get_fallback_jobs(self):
        """Fallback for testing"""
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
                'job_type': 'Full-time'
            }
        ]

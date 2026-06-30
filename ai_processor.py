import os
import json
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)

class JobAIProcessor:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv('DEEPSEEK_API_KEY'),
            base_url="https://api.deepseek.com/v1"
        )
        self.model = "deepseek-chat"
        self.profile = self._load_profile()

    def _load_profile(self):
        profile_path = os.path.join(os.path.dirname(__file__), 'profile.json')
        try:
            with open(profile_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error("profile.json not found!")
            return {
                "name": "Khalif Yusuf Mohamed",
                "title": "Chief of Staff",
                "skills": ["Project Management", "Strategic Planning"],
                "experience": [{"title": "Chief of Staff", "company": "Jubaland", "description": "..."}],
                "education": "Degree"
            }

    def process_job(self, job):
        try:
            logger.info(f"Processing: {job['title']} at {job['company']}")
            match_score = self._calculate_match_score(job)
            assessment = self._generate_assessment(job)
            tailored_cv = self._generate_tailored_cv(job)
            cover_letter = self._generate_cover_letter(job)
            answers = self._generate_screening_answers(job)
            return {
                'match_score': match_score,
                'assessment': assessment,
                'tailored_cv': tailored_cv,
                'cover_letter': cover_letter,
                'answers': answers
            }
        except Exception as e:
            logger.error(f"AI processing error: {e}")
            return self._get_fallback_results(job)

    def _calculate_match_score(self, job):
        profile_json = json.dumps(self.profile, indent=2)
        prompt = f"""You are a recruiter evaluating a candidate for a job.

JOB:
Title: {job['title']}
Company: {job['company']}
Description: {job['description'][:800]}...

CANDIDATE PROFILE:
{profile_json}

Analyze the match between the candidate and the job.
Consider:
1. Skills match (40%)
2. Experience relevance (30%)
3. Seniority level (20%)
4. Location/remote fit (10%)

Return ONLY a number between 0-100."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=50
        )
        try:
            score = int(response.choices[0].message.content.strip())
            return min(100, max(0, score))
        except:
            return 65

    def _generate_assessment(self, job):
        prompt = f"""You are a recruiter providing an honest assessment for this job.

JOB: {job['title']} at {job['company']}
Requirements: {job['description'][:400]}...
Candidate: {json.dumps(self.profile)}

Provide a balanced 3-4 sentence assessment covering:
1. Key strengths
2. Potential gaps
3. Overall recommendation (Strongly Recommend / Recommend / Consider / Not Recommended)

Be honest and professional."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200
        )
        return response.choices[0].message.content.strip()

    def _generate_tailored_cv(self, job):
        prompt = f"""Create a tailored CV for this job application.

JOB: {job['title']} at {job['company']}
Description: {job['description'][:600]}...
Candidate: {json.dumps(self.profile)}

Create a CV that highlights matching skills and experience.
Format:
### Professional Summary
### Skills
### Experience (with relevant bullet points)
### Education
### Certifications (if any)"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=600
        )
        return response.choices[0].message.content.strip()

    def _generate_cover_letter(self, job):
        prompt = f"""Write a professional cover letter for this application.

JOB: {job['title']} at {job['company']}
Description: {job['description'][:500]}...
Candidate: {json.dumps(self.profile)}

Make it 2-3 paragraphs, enthusiastic, and connect experience to the job."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=400
        )
        return response.choices[0].message.content.strip()

    def _generate_screening_answers(self, job):
        prompt = f"""Generate concise answers to common screening questions.

JOB: {job['title']} at {job['company']}
Candidate: {json.dumps(self.profile)}

Answer these (JSON):
- why_interested
- salary_expectation
- availability
- authorization
- key_strength
- challenge_example"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=400
        )
        try:
            return json.loads(response.choices[0].message.content.strip())
        except:
            return {
                "why_interested": f"I'm excited about {job['title']} at {job['company']}...",
                "salary_expectation": "Competitive based on experience and market rate",
                "availability": "2 weeks notice",
                "authorization": "Yes",
                "key_strength": "My strongest relevant skill is...",
                "challenge_example": "One challenge I solved was..."
            }

    def _get_fallback_results(self, job):
        return {
            'match_score': 70,
            'assessment': 'Candidate appears relevant. Recommended for consideration.',
            'tailored_cv': f"### Professional Summary\nExperienced professional in {', '.join(self.profile['skills'][:3])}...",
            'cover_letter': f"Dear Hiring Manager,\n\nI'm interested in {job['title']} at {job['company']}...",
            'answers': {
                "why_interested": "I'm interested because...",
                "salary_expectation": "Based on market rates",
                "availability": "2 weeks",
                "authorization": "Yes",
                "key_strength": "My strong point is...",
                "challenge_example": "I solved a challenge by..."
            }
        }

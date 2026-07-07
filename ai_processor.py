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
        """Load your CV/profile data"""
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
                "experience": [],
                "education": "Degree"
            }

    def process_job(self, job):
        """Process a job with DeepSeek AI - uses template content for better tailoring"""
        try:
            # Get the template content if available (from CV matching)
            template_content = job.get('template_content', '')
            
            logger.info(f"Processing job: {job['title']} at {job['company']}")
            
            match_score = self._calculate_match_score(job)
            assessment = self._generate_assessment(job)
            
            # Generate tailored CV using the template for guidance
            tailored_cv = self._generate_tailored_cv(job, template_content)
            
            cover_letter = self._generate_cover_letter(job, template_content)
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
        """Calculate match score using AI"""
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
        """Generate recruiter-style assessment"""
        prompt = f"""You are a recruiter providing an honest assessment.

JOB: {job['title']} at {job['company']}
Requirements: {job['description'][:400]}...
Candidate: {json.dumps(self.profile, indent=2)[:500]}

Provide a balanced 3-4 sentence assessment covering:
1. Key strengths
2. Potential gaps
3. Overall recommendation

Be honest and professional."""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200
        )
        return response.choices[0].message.content.strip()

    def _generate_tailored_cv(self, job, template_content=""):
        """
        Generate a tailored CV with a summary at the top
        Uses the matched template content for better tailoring
        """
        profile_json = json.dumps(self.profile, indent=2)
        
        # Use template content to guide tailoring if available
        tailoring_guidance = ""
        if template_content:
            tailoring_guidance = f"""
REFERENCE JOB TEMPLATE (use this to understand what kind of role this is):
{template_content}
"""
        
        prompt = f"""Create a tailored CV for this job application. IMPORTANT: Start with a strong professional summary at the very top.

JOB: {job['title']} at {job['company']}
Description: {job['description'][:600]}...
{tailoring_guidance}

CANDIDATE PROFILE: {profile_json}

Create a CV that:
1. **STARTS WITH A PROFESSIONAL SUMMARY** (2-3 sentences tailored to this specific role)
2. Highlights skills that match the job requirements
3. Rephrases experience to emphasize relevant achievements
4. Is concise and ATS-friendly

Format with clear sections:
### Professional Summary
### Skills
### Experience
### Education

Make the summary compelling and directly aligned with the job requirements."""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=600
        )
        return response.choices[0].message.content.strip()

    def _generate_cover_letter(self, job, template_content=""):
        """Generate a compelling cover letter"""
        tailoring_guidance = ""
        if template_content:
            tailoring_guidance = f"""
REFERENCE JOB TEMPLATE (use this to understand what kind of role this is):
{template_content[:300]}
"""
        
        prompt = f"""Write a professional cover letter for this job application.

JOB: {job['title']} at {job['company']}
Description: {job['description'][:500]}...
{tailoring_guidance}

Candidate Profile: {json.dumps(self.profile, indent=2)[:500]}

Cover letter should:
1. Express genuine enthusiasm for the role and company
2. Connect experience to specific job requirements
3. Highlight 2-3 key achievements relevant to the role
4. Be professional and concise (2-3 paragraphs)

Use a professional tone but make it personal and engaging."""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=400
        )
        return response.choices[0].message.content.strip()

    def _generate_screening_answers(self, job):
        """Generate answers to common screening questions"""
        prompt = f"""Generate professional answers to common screening questions.

JOB: {job['title']} at {job['company']}
Candidate Profile: {json.dumps(self.profile, indent=2)[:500]}

Provide concise answers for:
1. Why are you interested in this position?
2. What are your salary expectations?
3. What is your availability to start?
4. Are you authorized to work in this location?
5. What's your biggest strength for this role?

Format as JSON with keys: why_interested, salary_expectation, availability, authorization, key_strength"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=300
        )
        try:
            return json.loads(response.choices[0].message.content.strip())
        except:
            return {
                "why_interested": f"I'm excited about {job['title']} at {job['company']}...",
                "salary_expectation": "Competitive based on experience",
                "availability": "2 weeks notice",
                "authorization": "Yes",
                "key_strength": "My strongest relevant skill is..."
            }

    def _get_fallback_results(self, job):
        """Return fallback results if AI fails"""
        return {
            'match_score': 70,
            'assessment': 'Candidate appears to have relevant skills and experience.',
            'tailored_cv': f"### Professional Summary\nExperienced professional with skills in...\n\n### Experience\n{self.profile.get('experience', [{}])[0].get('description', '')}\n\n### Skills\n{', '.join(self.profile.get('skills', []))}",
            'cover_letter': f"Dear Hiring Manager,\n\nI'm writing to express my interest in the {job['title']} position at {job['company']}.",
            'answers': {
                "why_interested": f"I'm interested in {job['company']} because...",
                "salary_expectation": "Based on market rates",
                "availability": "2 weeks notice",
                "authorization": "Yes",
                "key_strength": "My strongest skill is..."
            }
        }

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
        
        # Load your CV/profile
        self.profile = self._load_profile()
    
    def _load_profile(self):
        """Load your CV and profile data"""
        # You can replace this with reading from a file
        return {
            "name": "Your Name",
            "title": "Software Engineer",
            "skills": ["Python", "React", "Node.js", "AWS", "Docker"],
            "experience": [
                {
                    "title": "Senior Developer",
                    "company": "Current Company",
                    "duration": "2020-Present",
                    "description": "Built scalable applications..."
                }
            ],
            "education": "BS Computer Science, Top University",
            "achievements": ["Led team of 5", "Increased performance by 40%"]
        }
    
    def process_job(self, job):
        """Process a job with DeepSeek AI"""
        try:
            # 1. Match score analysis
            match_score = self._calculate_match_score(job)
            
            # 2. Recruiter assessment
            assessment = self._generate_assessment(job)
            
            # 3. Tailored CV
            tailored_cv = self._generate_tailored_cv(job)
            
            # 4. Cover letter
            cover_letter = self._generate_cover_letter(job)
            
            # 5. Screening questions
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
        prompt = f"""
        Compare the following job description with my profile and return a match score (0-100):
        
        Job: {job['title']} at {job['company']}
        Description: {job['description'][:500]}...
        
        My Profile:
        Skills: {', '.join(self.profile['skills'])}
        Experience: {self.profile['experience'][0]['description']}
        
        Return ONLY a number between 0-100.
        """
        
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
            return 75  # Default score
    
    def _generate_assessment(self, job):
        """Generate recruiter-style assessment"""
        prompt = f"""
        Provide a recruiter-style assessment (2-3 sentences) for my fit for this role:
        
        Job: {job['title']} at {job['company']}
        Requirements: {job['description'][:300]}...
        
        My Profile: {json.dumps(self.profile)}
        
        Assessment should be professional, honest, and highlight specific strengths.
        """
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=150
        )
        
        return response.choices[0].message.content.strip()
    
    def _generate_tailored_cv(self, job):
        """Generate tailored CV draft"""
        prompt = f"""
        Create a tailored CV for this job application. Keep it concise and relevant:
        
        Job: {job['title']} at {job['company']}
        Description: {job['description'][:500]}...
        
        My Profile: {json.dumps(self.profile)}
        
        Return the CV as plain text with clear sections: Summary, Skills, Experience, Education.
        Focus on matching the job requirements.
        """
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=400
        )
        
        return response.choices[0].message.content.strip()
    
    def _generate_cover_letter(self, job):
        """Generate tailored cover letter"""
        prompt = f"""
        Write a professional cover letter for this job application:
        
        Job: {job['title']} at {job['company']}
        Description: {job['description'][:500]}...
        
        My Profile: {json.dumps(self.profile)}
        
        Cover letter should be 2-3 paragraphs, professional, and highlight relevant experience.
        """
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300
        )
        
        return response.choices[0].message.content.strip()
    
    def _generate_screening_answers(self, job):
        """Generate answers to common screening questions"""
        prompt = f"""
        Generate answers to common screening questions for this role:
        
        Job: {job['title']} at {job['company']}
        My Profile: {json.dumps(self.profile)}
        
        Answer these questions concisely:
        1. Why do you want to work here?
        2. What are your salary expectations?
        3. What's your availability to start?
        4. Are you authorized to work in this country?
        5. What's your biggest strength relevant to this role?
        
        Return as JSON object.
        """
        
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
                "why_work": "I'm excited about the opportunity...",
                "salary": "Competitive based on market rate",
                "availability": "2 weeks notice",
                "authorization": "Yes, authorized to work",
                "strength": "My strongest relevant skill is..."
            }
    
    def _get_fallback_results(self, job):
        """Return fallback results if AI fails"""
        return {
            'match_score': 70,
            'assessment': 'Good match based on skills and experience.',
            'tailored_cv': f"CV for {job['title']} at {job['company']}...",
            'cover_letter': f"Dear Hiring Manager, I'm interested in {job['title']}...",
            'answers': {
                "why_work": "I'm passionate about the role...",
                "salary": "Competitive market rate",
                "availability": "2 weeks notice",
                "authorization": "Yes",
                "strength": "My relevant experience..."
            }
        }

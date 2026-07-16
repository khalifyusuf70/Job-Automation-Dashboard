import os
import json
import logging
import numpy as np

logger = logging.getLogger(__name__)

class CVMatchingAgent:
    def __init__(self):
        # Use a TINY model that uses ~50MB instead of 500MB
        # This model is fast, small, and still effective for semantic matching
        try:
            from sentence_transformers import SentenceTransformer, util
            self.model = SentenceTransformer('all-MiniLM-L3-v2')  # Much smaller!
            self._load_templates()
            logger.info("CVMatchingAgent initialized with tiny model")
        except ImportError as e:
            logger.error(f"Failed to import sentence_transformers: {e}")
            self.model = None
            self.templates = []
            self.template_embeddings = []
            logger.warning("CV matching disabled - running without filtering")
        except Exception as e:
            logger.error(f"Failed to initialize model: {e}")
            self.model = None
            self.templates = []
            self.template_embeddings = []
            logger.warning("CV matching disabled - running without filtering")
        
    def _load_templates(self):
        """Load your 6 target job descriptions as templates"""
        if self.model is None:
            return
            
        # Your 6 target job descriptions
        templates_data = [
            {
                'filename': 'grants_specialist.txt',
                'content': """
Job Title: Grants Specialist
Industry: International Development, NGOs, Humanitarian
Key Responsibilities: Grants management, compliance, partnership coordination, donor reporting, proposal development, due diligence, capacity building, risk management, MEAL systems
Required Skills: Grant management, donor compliance, proposal writing, budget tracking, risk assessment, partner vetting, reporting
Experience: 5+ years in grants management, experience with multi-donor facilities, USAID/UN/DFID donors
Education: Bachelor's degree in relevant field
Key Competencies: Attention to detail, compliance, stakeholder engagement, report writing
"""
            },
            {
                'filename': 'head_of_research.txt',
                'content': """
Job Title: Head of Research / Research Coordinator
Industry: International Development, NGOs, Health, Academia
Key Responsibilities: Research strategy, study design, qualitative & quantitative research, product research, UX research, analysis, dissemination, team leadership, donor engagement
Required Skills: Research design, data analysis, qualitative methods, quantitative methods, team management, stakeholder engagement
Experience: 7+ years in research leadership, experience with randomized controlled trials, academic publications
Education: Master's or PhD in relevant field
Key Competencies: Analytical thinking, scientific rigor, leadership, communication
"""
            },
            {
                'filename': 'head_of_data_analytics.txt',
                'content': """
Job Title: Head of Data & Analytics
Industry: International Development, NGOs, Technology, Health
Key Responsibilities: Data strategy, analytics, impact measurement, data systems, dashboards, machine learning, team leadership, data governance
Required Skills: Data analytics, statistical methods, data visualization, dashboard development, team leadership, data governance
Experience: 7+ years in data analytics leadership, experience with health data, programme evaluation
Education: Master's in Data Science, Statistics, or related field
Key Competencies: Analytical thinking, data storytelling, leadership, strategic planning
"""
            },
            {
                'filename': 'policy_consultant.txt',
                'content': """
Job Title: Policy Consultant
Industry: International Development, NGOs, Government, Consulting
Key Responsibilities: Policy analysis, document review, strategic consultation, regulatory compliance, proposal writing, research, stakeholder engagement
Required Skills: Policy analysis, document drafting, strategic consulting, regulatory compliance, research, stakeholder engagement
Experience: 5+ years in policy analysis or consulting, experience with government or international organizations
Education: Master's in Public Policy, Law, or related field
Key Competencies: Analytical thinking, writing, strategic thinking, stakeholder engagement
"""
            },
            {
                'filename': 'country_director.txt',
                'content': """
Job Title: Country Director / Regional Director / Regional Coordinator
Industry: International Development, NGOs, Humanitarian
Key Responsibilities: Strategic leadership, programme management, fundraising, donor relations, partnership development, team leadership, political analysis, representation
Required Skills: Strategic planning, programme management, fundraising, donor engagement, partnership development, team leadership, humanitarian analysis
Experience: 8+ years in senior leadership, experience with humanitarian response, civil society, peacebuilding
Education: Master's in relevant field
Key Competencies: Leadership, strategic thinking, stakeholder engagement, crisis management
"""
            },
            {
                'filename': 'merl_specialist.txt',
                'content': """
Job Title: Monitoring, Evaluation, Research and Learning (MERL) Specialist
Industry: International Development, NGOs, Health
Key Responsibilities: MERL strategy, measurement frameworks, data quality assurance, research design, cost-effectiveness analysis, learning agenda, team management
Required Skills: Monitoring & evaluation, research design, data analysis, learning frameworks, cost-effectiveness analysis, team leadership
Experience: 7+ years in MERL leadership, experience with donor reporting, program evaluation
Education: Master's in relevant field
Key Competencies: Analytical thinking, evidence-based decision making, leadership, communication
"""
            }
        ]
        
        # Load templates into memory
        self.templates = []
        self.template_embeddings = []
        for template_data in templates_data:
            self.templates.append({
                'filename': template_data['filename'],
                'content': template_data['content']
            })
            # Precompute embeddings for fast matching
            embedding = self.model.encode(template_data['content'], convert_to_tensor=True)
            self.template_embeddings.append(embedding)
            logger.info(f"Loaded template: {template_data['filename']}")
        
        logger.info(f"Loaded {len(self.templates)} JD templates")
    
    def match_job_against_templates(self, job_text, threshold=0.30):
        """
        Match a job description against all 6 loaded templates
        Returns True if job matches at least one template above threshold
        """
        if self.model is None or not self.template_embeddings:
            return True, 0.0, None, ""
            
        try:
            # Encode the job description once
            job_embedding = self.model.encode(job_text, convert_to_tensor=True)
            
            # Calculate similarity with all templates
            best_score = 0.0
            best_template = None
            best_index = -1
            
            for i, template_embedding in enumerate(self.template_embeddings):
                from sentence_transformers import util
                similarity = util.pytorch_cos_sim(job_embedding, template_embedding).item()
                
                if similarity > best_score:
                    best_score = similarity
                    best_template = self.templates[i]['filename']
                    best_index = i
            
            # Get the matched template content for CV tailoring
            matched_content = self.templates[best_index]['content'] if best_index >= 0 else ""
            
            return best_score >= threshold, best_score, best_template, matched_content
            
        except Exception as e:
            logger.error(f"Error matching job: {e}")
            return True, 0.0, None, ""
    
    def filter_jobs_by_template_match(self, jobs, threshold=0.30):
        """
        Filter jobs, keeping only those that match at least one of your 6 JD templates
        """
        if self.model is None or not self.template_embeddings:
            logger.info("CV matching disabled - processing all jobs")
            return jobs
            
        matched_jobs = []
        total = len(jobs)
        for idx, job in enumerate(jobs):
            job_text = f"{job.get('title', '')} {job.get('description', '')}"
            is_match, score, template, template_content = self.match_job_against_templates(job_text, threshold)
            
            if is_match:
                job['cv_match_score'] = round(score * 100, 2)
                job['matched_template'] = template
                job['template_content'] = template_content
                matched_jobs.append(job)
                logger.info(f"✅ Matched: {job.get('title')} (score: {job['cv_match_score']}%, template: {template})")
            else:
                logger.info(f"❌ Rejected: {job.get('title')} (score: {round(score * 100, 2)}%)")
            
            # Log progress every 10 jobs
            if (idx + 1) % 10 == 0:
                logger.info(f"Processed {idx + 1}/{total} jobs")
                
        logger.info(f"Filtered: {len(matched_jobs)} jobs matched out of {len(jobs)}")
        return matched_jobs
    
    def get_template_content(self, filename):
        """Get the content of a specific template"""
        for template in self.templates:
            if template['filename'] == filename:
                return template['content']
        return None
    
    def list_templates(self):
        """List all loaded templates"""
        return [t['filename'] for t in self.templates]

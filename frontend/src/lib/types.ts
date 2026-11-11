export type SizeCategory = "small" | "medium" | "large" | null;

export interface Company {
  id: number | null;
  name: string;
  logo_url?: string | null;
  size_category: SizeCategory;
  size_label: string;
  employee_count?: number | null;
  size_source?: string | null;
  company_type?: string | null;
  website?: string | null;
  careers_url?: string | null;
}

export interface JobSourceLink {
  key: string;
  name: string;
  url?: string | null;
  is_official: boolean;
  first_seen_at: string;
  last_seen_at: string;
  status: string;
}

export interface Match {
  score: number;
  matched_skills: string[];
  missing_skills: string[];
  experience_fit?: string | null;
  explanation?: string | null;
  gaps: string[];
  is_new: boolean;
  hidden: boolean;
  computed_at: string;
  breakdown?: Record<string, { score: number; weight: number; points: number; note: string }>;
  llm_explanation?: string | null;
}

export interface Job {
  id: number;
  title: string;
  company: Company;
  location: string;
  work_mode: "remote" | "hybrid" | "onsite" | "unknown";
  employment_type: string;
  experience: string;
  experience_min_years?: number | null;
  experience_max_years?: number | null;
  salary: string;
  date_posted?: string | null;
  first_seen_at: string;
  last_seen_at: string;
  last_verified_at?: string | null;
  status: "active" | "unavailable";
  is_official: boolean;
  apply_url?: string | null;
  sources: JobSourceLink[];
  skills: string[];
  saved: boolean;
  match: Match | null;
  description?: string;
  saved_at?: string;
  notes?: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export type EmploymentType = "full_time" | "internship" | "contract" | "part_time" | "freelance";

export interface ExperienceItem {
  title?: string | null;
  company?: string | null;
  start?: string | null;
  end?: string | null;
  employment_type?: EmploymentType | null;
  responsibilities?: string[];
  months?: number | null;
  relevant?: boolean | null;
}

export interface EducationItem {
  degree?: string | null;
  institution?: string | null;
  year?: string | null;
  level?: string | null;
}

export interface ProjectItem {
  name?: string | null;
  description?: string | null;
  technologies: string[];
}

export interface Preferences {
  preferred_roles: string[];
  min_experience_years: number;
  max_experience_years: number;
  preferred_locations: string[];
  countries: string[];
  remote_preference: "any" | "remote" | "hybrid" | "onsite";
  company_sizes: ("small" | "medium" | "large" | "unknown")[];
  preferred_technologies: string[];
  min_match_score: number;
  posted_within_days: number;
  prioritize_small_medium: boolean;
  weights?: Record<string, number> | null;
}

export interface Profile {
  id: number;
  candidate?: string | null;
  email?: string | null;
  phone?: string | null;
  location?: string | null;
  summary?: string | null;
  experience_level?: string | null;
  total_experience_months: number;
  professional_experience_months: number;
  internship_experience_months: number;
  relevant_experience_months: number;
  education_level?: string | null;
  experience: ExperienceItem[];
  education: EducationItem[];
  skills: string[];
  skills_by_category: Record<string, string[]>;
  projects: ProjectItem[];
  certifications: string[];
  previous_companies: string[];
  job_roles: string[];
  transferable_skills: string[];
  preferred_industries: string[];
  analysis_method: string;
  edited_by_user: boolean;
  preferences: Preferences;
  resume?: { id: number; filename: string; uploaded_at: string; size_bytes: number; encrypted: boolean };
  updated_at: string;
}

export interface SearchLog {
  id: number;
  ts: string;
  level: string;
  source?: string | null;
  message: string;
}

export interface SourceResult {
  status: string;
  count: number;
  error?: string;
  seconds?: number;
}

export interface SearchSession {
  id: number;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  current_step?: string | null;
  keywords: string[];
  stats: Record<string, number>;
  source_results: Record<string, SourceResult>;
  error?: string | null;
  cancel_requested: boolean;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  logs?: SearchLog[];
  delta_matching?: number;
}

export interface DashboardStats {
  profile: null | {
    candidate?: string | null;
    experience_level?: string | null;
    professional_experience_months: number;
    internship_experience_months: number;
    skills_count: number;
    top_skills: string[];
    job_roles: string[];
    updated_at: string;
  };
  min_match_score: number;
  total_jobs: number;
  matching_jobs: number;
  highly_relevant: number;
  small_company_jobs: number;
  medium_company_jobs: number;
  new_jobs: number;
  official_jobs: number;
  companies_tracked: number;
  score_distribution: Record<string, number>;
  last_search: null | { id: number; status: string; created_at: string; finished_at?: string | null; progress: number };
  last_completed_search: null | { id: number; finished_at?: string | null; stats: Record<string, number> };
}

export interface CompanyRow {
  id: number;
  name: string;
  website?: string | null;
  domain?: string | null;
  careers_url?: string | null;
  logo_url?: string | null;
  size_category: SizeCategory;
  size_label: string;
  employee_count?: number | null;
  size_source?: string | null;
  company_type?: string | null;
  ats_type?: string | null;
  discovered_via?: string | null;
  first_discovered_at: string;
  last_checked_at?: string | null;
  last_check_status?: string | null;
  open_jobs_count: number;
  matching_jobs: number;
  best_score?: number | null;
}

export interface SourceRow {
  key: string;
  name: string;
  kind: string;
  status: string;
  enabled: boolean;
  requires_credentials: boolean;
  is_official_company_source: boolean;
  notes?: string | null;
  base_url?: string | null;
  last_run_at?: string | null;
  last_error?: string | null;
  last_job_count: number;
}

/* ---------------------------------------------------------------- application emails */
export type EmailStatus = "pending" | "ready" | "sending" | "sent" | "failed" | "skipped";

export interface GmailAccount {
  id: number;
  email: string;
  is_connected: boolean;
  last_error: string | null;
  connected_at: string;
  last_used_at: string | null;
}

export interface GmailAccountsResp {
  configured: boolean;
  redirect_uri: string;
  default_account_id: number | null;
  accounts: GmailAccount[];
}

export interface EmailTemplate {
  id: number;
  name: string;
  subject: string;
  body: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface JobEmail {
  id: number;
  job_id: number;
  job_title: string | null;
  company_name: string | null;
  job_url: string | null;
  job_status: string | null;
  match_score: number | null;
  recipient_email: string | null;
  recipient_source: "posting" | "manual" | null;
  hr_name: string | null;
  sender_account_id: number | null;
  sender_email: string | null;
  template_id: number | null;
  template_name: string | null;
  subject: string;
  body: string;
  resume_id: number | null;
  attach_resume: boolean;
  mode: "manual" | "auto";
  status: EmailStatus;
  gmail_message_id: string | null;
  sent_at: string | null;
  error_message: string | null;
  attempts: number;
  edited_by_user: boolean;
  created_at: string;
  updated_at: string;
}

export interface EmailSettings {
  auto_send_enabled: boolean;
  daily_limit: number;
  daily_limit_max: number;
  auto_min_score: number;
  default_account_id: number | null;
  default_template_id: number | null;
  attach_resume: boolean;
  resume_link: string;
  detect_on_run: boolean;
}

export interface EmailStats {
  by_status: Record<EmailStatus, number>;
  sent_last_24h: number;
  daily_limit: number;
  auto_send_enabled: boolean;
}

export interface ResumeFile {
  id: number;
  filename: string;
  uploaded_at: string;
  is_active: boolean;
  size_bytes: number;
}

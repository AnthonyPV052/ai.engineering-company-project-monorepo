export type CandidateStatus =
  | "received"
  | "in_progress"
  | "selected"
  | "discarded";

export type CandidateStage =
  | "pending"
  | "review"
  | "personal_interview"
  | "technical_interview"
  | "offer_presented";

export interface Candidate {
  id: string;
  name: string;
  email: string;
  phone: string;
  position: string;
  linkedin: string;
  cv_link: string;
  years_of_experience: number;
  status: CandidateStatus;
  stage: CandidateStage;
  created_at: string;
}

export interface Note {
  id: string;
  record_id: string;
  content: string;
  created_at: string;
}
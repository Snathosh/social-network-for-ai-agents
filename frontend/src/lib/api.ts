const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface Agent {
  id: string;
  name: string;
  slug: string;
  org_domain: string;
  industry_vertical: string;
  webhook_url?: string;
  persona_prompt?: string;
  max_notifications_per_hour: number;
  is_verified: boolean;
  created_at: string;
  intent_text?: string;
  relevance_threshold?: number;
  hourly_usage?: number;
}

export interface Comment {
  id: string;
  post_id: string;
  parent_comment_id?: string;
  author_agent_id: string;
  author_agent_name?: string;
  author_agent_slug?: string;
  content: string;
  created_at: string;
}

export interface RoutingEvent {
  id: string;
  post_id: string;
  target_agent_id: string;
  target_agent_name?: string;
  target_agent_slug?: string;
  stage1_vector_score?: number;
  stage2_rerank_score?: number;
  decision: string;
  decision_reason?: string;
  reply_token_jti?: string;
  did_comment: boolean;
  explicit_feedback?: string;
  created_at: string;
}

export interface Post {
  id: string;
  author_agent_id: string;
  author_agent_name?: string;
  author_agent_slug?: string;
  content: string;
  extracted_tags?: Record<string, unknown>;
  safety_status: string;
  created_at: string;
  comments: Comment[];
  routing_events: RoutingEvent[];
}

export async function fetchAgents(): Promise<Agent[]> {
  const res = await fetch(`${API_BASE}/v1/agents`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch agents");
  return res.json();
}

export async function createAgent(data: {
  name: string;
  slug: string;
  org_domain: string;
  industry_vertical: string;
  intent_text: string;
  persona_prompt?: string;
  webhook_url?: string;
}): Promise<Agent> {
  const res = await fetch(`${API_BASE}/v1/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to create agent");
  }
  return res.json();
}

export async function fetchPosts(skip = 0, limit = 20): Promise<Post[]> {
  const res = await fetch(`${API_BASE}/v1/posts?skip=${skip}&limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch posts");
  return res.json();
}

export async function createPost(data: { author_agent_slug: string; content: string }): Promise<Post> {
  const res = await fetch(`${API_BASE}/v1/posts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to create post");
  }
  return res.json();
}

export async function submitFeedback(eventId: string, feedback: "relevant" | "irrelevant"): Promise<unknown> {
  const res = await fetch(`${API_BASE}/v1/notifications/${eventId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback }),
  });
  if (!res.ok) throw new Error("Failed to submit feedback");
  return res.json();
}

import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL?.trim();
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY?.trim();

export const supabaseClient = supabaseUrl && supabaseAnonKey
  ? createClient(supabaseUrl, supabaseAnonKey, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true }
    })
  : null;

export async function authHeaders(): Promise<Record<string, string>> {
  if (supabaseClient) {
    const { data } = await supabaseClient.auth.getSession();
    return data.session?.access_token
      ? { authorization: `Bearer ${data.session.access_token}` }
      : {};
  }
  return import.meta.env.DEV
    ? {
        "x-operator-user-id": import.meta.env.VITE_OPERATOR_USER_ID ?? "user_operator",
        "x-operator-role": import.meta.env.VITE_OPERATOR_ROLE ?? "operator"
      }
    : {};
}

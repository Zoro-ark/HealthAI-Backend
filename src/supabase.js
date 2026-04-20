import { createClient } from '@supabase/supabase-js';
import dotenv from 'dotenv';

dotenv.config();

const SUPABASE_URL = "https://shdbkdnmaqbiqiiwsaga.supabase.co";
const SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNoZGJrZG5tYXFiaXFpaXdzYWdhIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ3Nzk4NDksImV4cCI6MjA5MDM1NTg0OX0.URY6SWmPA-Irds82mn4q_S4-zMQx13eOgesOoVjjd3Q";

const supabaseUrl = SUPABASE_URL;
const supabaseKey = SUPABASE_ANON_KEY;
console.log(SUPABASE_URL, SUPABASE_ANON_KEY);
// if (SUPABASE_URL || SUPABASE_ANON_KEY) {
//   console.error("❌ Missing SUPABASE_URL or SUPABASE_ANON_KEY in environment variables.");
// }

export const supabase = createClient(supabaseUrl, supabaseKey);

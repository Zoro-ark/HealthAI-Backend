-- Run this script in your Supabase SQL Editor

-- 1. Add user_id to doctor_verifications
ALTER TABLE public.doctor_verifications 
ADD COLUMN user_id UUID REFERENCES public.users(id) ON DELETE CASCADE;

-- 2. Add user_id to doctors
ALTER TABLE public.doctors 
ADD COLUMN user_id UUID REFERENCES public.users(id) ON DELETE CASCADE;

-- 3. Provide indices for performance on foreign keys
CREATE INDEX IF NOT EXISTS idx_doctor_verif_user_id ON public.doctor_verifications(user_id);
CREATE INDEX IF NOT EXISTS idx_doctors_user_id ON public.doctors(user_id);

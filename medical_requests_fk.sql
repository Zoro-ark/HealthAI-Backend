-- Create a direct foreign key linking medical_requests to the users table
-- We link it to clerk_id because patient_id in medical_requests is a text representation of the Clerk user.

ALTER TABLE public.medical_requests 
ADD CONSTRAINT medical_requests_users_clerk_id_fkey 
FOREIGN KEY (patient_id) 
REFERENCES public.users(clerk_id) 
ON DELETE CASCADE;

-- Reload the schema so Supabase API picks up the new join capable relationship
NOTIFY pgrst, 'reload schema';

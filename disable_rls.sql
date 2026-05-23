-- 1. Disable RLS on frontend tables so they can be written to without strict policies during development
ALTER TABLE IF EXISTS public.patients DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.patient_docs DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.medical_requests DISABLE ROW LEVEL SECURITY;

-- 2. Storage buckes need an explicit RLS policy to allow uploads (even if marked 'Public', that only allows reading!)
-- This creates a policy that allows anyone to upload files to your 3 main buckets.
CREATE POLICY "Allow public uploads" ON storage.objects 
FOR INSERT WITH CHECK (
  bucket_id = 'patient_documents' OR 
  bucket_id = 'medical-docs' OR 
  bucket_id = 'doctor_documents'
);

-- This allows reading them back
CREATE POLICY "Allow public reads" ON storage.objects 
FOR SELECT USING (
  bucket_id = 'patient_documents' OR 
  bucket_id = 'medical-docs' OR 
  bucket_id = 'doctor_documents'
);

-- This allows updates (sometimes needed if the frontend overwrites)
CREATE POLICY "Allow public updates" ON storage.objects 
FOR UPDATE USING (
  bucket_id = 'patient_documents' OR 
  bucket_id = 'medical-docs' OR 
  bucket_id = 'doctor_documents'
);

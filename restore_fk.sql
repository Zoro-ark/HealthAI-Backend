-- Restore the foreign key on 'visits' that was deleted 
-- when the 'users' table was recreated with DROP CASCADE previously.

ALTER TABLE public.visits 
ADD CONSTRAINT visits_user_id_fkey 
FOREIGN KEY (user_id) 
REFERENCES public.users(id) 
ON DELETE CASCADE;

-- Note: Sometimes Supabase takes a second to reload its API schema cache.
-- If the error persists for a few seconds after running this, run:
-- NOTIFY pgrst, 'reload schema';

-- Drop the existing users table if it exists
-- WARNING: This will delete all existing data in the users table and any objects depending on it!
DROP TABLE IF EXISTS public.users CASCADE;

-- Recreate the merged users table
CREATE TABLE public.users (
  id uuid not null default extensions.uuid_generate_v4 (),
  clerk_id text not null,
  email text not null,
  name text not null,
  role text null default 'unknown'::text,
  is_verified boolean null default false,
  age integer null,
  budget text null,
  availability_days integer null,
  visa_status text null,
  created_at timestamp with time zone not null default timezone ('utc'::text, now()),
  updated_at timestamp with time zone not null default timezone ('utc'::text, now()),
  assigned_doctor_id text null,
  assigned_doctor_name text null,
  constraint users_pkey primary key (id),
  constraint users_clerk_id_key unique (clerk_id),
  constraint users_email_key unique (email),
  constraint users_role_check check (
    (
      role = any (
        array['unknown'::text, 'patient'::text, 'doctor'::text, 'admin'::text]
      )
    )
  ),
  constraint users_visa_status_check check (
    (
      visa_status = any (
        array[
          'indian_citizen'::text,
          'not_indian_citizen'::text,
          'other'::text
        ]
      )
    )
  )
) TABLESPACE pg_default;

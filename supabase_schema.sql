-- Run this script in your Supabase SQL Editor

-- 1. Create the Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clerk_id TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role TEXT DEFAULT 'user' CHECK (role IN ('user', 'doctor', 'admin')),
    is_verified BOOLEAN DEFAULT false,
    age INTEGER,
    budget TEXT,
    availability_days INTEGER,
    visa_status TEXT CHECK (visa_status IN ('indian_citizen', 'not_indian_citizen', 'other')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. Create the Visits table
CREATE TABLE visits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    pseudonym_id TEXT NOT NULL,
    visit_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    visit_type TEXT DEFAULT 'initial' CHECK (visit_type IN ('initial', 'follow_up', 'emergency', 'routine_checkup')),
    chief_complaint TEXT,
    status TEXT DEFAULT 'requested' CHECK (status IN ('in_progress', 'completed', 'cancelled', 'requested')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 3. Create the Ingests table (replaces the embedded ingests array)
CREATE TABLE ingests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    visit_id UUID REFERENCES visits(id) ON DELETE CASCADE,
    ingest_id TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK (type IN ('prescription', 'lab_report', 'imaging', 'clinical_notes')),
    s3_key TEXT NOT NULL,
    s3_bucket TEXT NOT NULL,
    s3_region TEXT NOT NULL,
    original_filename TEXT,
    file_size INTEGER,
    content_type TEXT,
    upload_timestamp TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

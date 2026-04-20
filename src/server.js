import express from "express";
import dotenv from "dotenv";
import cors from "cors";
import { supabase } from "./supabase.js";
import multer from "multer";
import path from "path";
import shortUUID from "short-uuid";

dotenv.config();
const app = express();

// --- Storage Setup (Memory Storage for Supabase Upload) ---
const upload = multer({
    storage: multer.memoryStorage(),
    limits: { fileSize: 10 * 1024 * 1024 } // 10MB limit
});

// CORS configuration
app.use(
    cors({
        origin: "*", // allow all origins
        methods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allowedHeaders: ["*"], // allow all headers
        exposedHeaders: ["*"]
    })
);

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// --- Middleware to get User from Supabase based on Clerk ID ---
const getUserMiddleware = async (req, res, next) => {
    // req.header() is case-insensitive in Express, unlike req.headers[]
    const authHeader = req.header('Authorization');

    // If it starts with "Bearer ", take the second part. Otherwise, assume the exact string is the token.
    const clerkId = authHeader?.startsWith('Bearer ') ? authHeader.split(' ')[1] : authHeader;

    console.log("Extracted Clerk ID:", clerkId);

    // --- Completely bypass auth requirement for addUser ---
    if (req.path === '/addUser' && req.method === 'POST') {
        return next();
    }

    if (!clerkId) {
        if (req.path === '/user/status' && req.method === 'GET') {
            req.user = null;
            return next();
        }
        return res.status(401).json({ message: 'Unauthorized: No Clerk ID provided' });
    }

    try {
        const { data: user, error } = await supabase
            .from('users')
            .select('*')
            .eq('clerk_id', clerkId)
            .maybeSingle();

        if (error) throw error;

        if (!user) {
            if (req.path === '/user/status' && req.method === 'GET') {
                req.user = null;
                return next();
            }
            return res.status(404).json({ message: 'User not found in DB' });
        }
        req.user = user;
        next();
    } catch (err) {
        console.error("Middleware error:", err);
        res.status(500).json({ message: "Server error in middleware" });
    }
};

app.use('/api', getUserMiddleware);

// Routes
app.get("/", (req, res) => {
    res.json({ message: "Supabase Server running successfully 🚀" });
});

app.post("/api/addUser", async (req, res) => {
    try {
        let { clerkId, email, name, role } = req.body;

        // Map 'patient' to 'user' to bypass strict Supabase CHECK constraint
        if (role === 'patient') {
            role = 'user';
        }

        if (!clerkId || !email || !name) {
            return res.status(400).json({ message: "Missing required fields: clerkId, email, name" });
        }

        // Check if user exists
        const { data: existingUser } = await supabase
            .from('users')
            .select('*')
            .eq('clerk_id', clerkId)
            .maybeSingle();

        if (!existingUser) {
            // Create user
            const { data: newUser, error } = await supabase
                .from('users')
                .insert({ clerk_id: clerkId, email, name: name, role: role || 'user' })
                .select()
                .single();

            if (error) {
                if (error.code === '23505') { // Postgres unique violation (e.g. email exists)
                    return res.status(409).json({ message: "Email already exists" });
                }
                throw error;
            }

            return res.status(201).json({ message: "User created", user: newUser });
        }

        return res.status(200).json({ message: "User already exists", user: existingUser });
    } catch (err) {
        console.error("Add user error:", err);
        return res.status(500).json({ message: err.message || "Server error" });
    }
});

// --- Verification Endpoint ---
app.post("/api/user/verify", async (req, res) => {
    if (!req.user) return res.status(401).json({ message: "Unauthorized" });

    try {
        const { name, age, budget, availabilityDays, visaStatus } = req.body;

        if (!name || !age || !budget || !availabilityDays || !visaStatus) {
            return res.status(400).json({ message: "Missing verification fields" });
        }

        const { data: updatedUser, error } = await supabase
            .from('users')
            .update({
                name,
                age: parseInt(age, 10),
                budget,
                availability_days: parseInt(availabilityDays, 10),
                visa_status: visaStatus,
                is_verified: true
            })
            .eq('id', req.user.id)
            .select()
            .single();

        if (error) throw error;

        res.status(200).json({ message: "User verified successfully", user: updatedUser });
    } catch (err) {
        console.error("Verification error:", err);
        res.status(500).json({ message: "Server error during verification" });
    }
});

// --- User Status Endpoint ---
app.get("/api/user/status", (req, res) => {
    if (req.user) {
        res.status(200).json({
            isVerified: req.user.is_verified || false,
            clerkId: req.user.clerk_id,
            userId: req.user.id,
            assignedDoctorName: req.user.assigned_doctor_name || null
        });
    } else {
        res.status(200).json({ isVerified: false, clerkId: null, userId: null });
    }
});

// --- Admin: Get Verified Patients ---
app.get("/api/admin/patients", async (req, res) => {
    // Basic auth check - ideally you'd also check if req.user.role === 'admin'
    if (!req.user || req.user.role !== 'admin') {
        return res.status(403).json({ message: "Forbidden: Admin access only" });
    }

    try {
        // Fetch all verified patients and their visits to see symptoms
        const { data: patients, error } = await supabase
            .from('users')
            .select(`
                *,
                medical_requests(symptoms, created_at)
            `)
            .in('role', ['patient', 'user']);

        if (error) throw error;
        
        const formattedPatients = patients.map(p => ({
            ...p,
            name: p.full_name,
            age: p.age || 0,
            budget: p.budget || 'Unspecified',
            visa_status: p.visa_status || 'Pending'
        }));
        
        res.status(200).json(formattedPatients);
    } catch (err) {
        console.error("Error fetching admin patients:", err);
        res.status(500).json({ message: "Server error fetching patients" });
    }
});

// --- Admin: Assign Doctor to Patient ---
app.post("/api/admin/assign", async (req, res) => {
    if (!req.user || req.user.role !== 'admin') {
        return res.status(403).json({ message: "Forbidden: Admin access only" });
    }

    try {
        const { patientId, doctorId, doctorName } = req.body;

        if (!patientId || !doctorId || !doctorName) {
            return res.status(400).json({ message: "Missing required assignment fields" });
        }

        // The doctorId passed from the frontend is actually the doctor_verifications.id
        // We need to fetch the real doctors.id to satisfy the foreign key constraint
        const { data: docVerify } = await supabase.from('doctor_verifications').select('user_id').eq('id', doctorId).maybeSingle();
        if (!docVerify) return res.status(404).json({ message: "Doctor verification record not found" });

        const { data: realDoctor } = await supabase.from('doctors').select('id').eq('user_id', docVerify.user_id).maybeSingle();
        if (!realDoctor) return res.status(404).json({ message: "Doctor profile not established yet. Ensure they are fully verified." });

        const actualDoctorId = realDoctor.id;

        const { data: updatedUser, error } = await supabase
            .from('users')
            .update({
                assigned_doctor_id: actualDoctorId,
                assigned_doctor_name: doctorName
            })
            .eq('id', patientId)
            .select()
            .single();

        if (error) throw error;

        // Insert into appointments table mapping the true doctor.id to this patient
        const { data: existingAppt } = await supabase
            .from('appointments')
            .select('id')
            .eq('patient_id', updatedUser.clerk_id)
            .maybeSingle();

        if (existingAppt) {
            const { error: updateErr } = await supabase.from('appointments').update({ doctor_id: actualDoctorId }).eq('id', existingAppt.id);
            if (updateErr) console.error("Appointments Update Error:", updateErr);
        } else {
            const { error: insertErr } = await supabase.from('appointments').insert({
                patient_id: updatedUser.clerk_id,
                doctor_id: actualDoctorId,
                status: 'scheduled',
                appointment_date: new Date().toISOString()
            });
            if (insertErr) console.error("Appointments Insert Error:", insertErr);
        }


        res.status(200).json({ message: "Doctor assigned successfully", patient: updatedUser });
    } catch (err) {
        console.error("Error assigning doctor:", err);
        res.status(500).json({ message: "Server error during doctor assignment" });
    }
});

// --- Admin: Get All Doctor Verifications ---
app.get("/api/admin/doctors", async (req, res) => {
    if (!req.user || req.user.role !== 'admin') {
        return res.status(403).json({ message: "Forbidden: Admin access only" });
    }

    try {
        const { data: doctors, error } = await supabase
            .from('doctor_verifications')
            .select('*')
            .order('created_at', { ascending: false });

        if (error) throw error;
        
        res.status(200).json(doctors);
    } catch (err) {
        console.error("Error fetching doctor verifications:", err);
        res.status(500).json({ message: "Server error fetching doctor verifications" });
    }
});

// --- Admin: Update Doctor Verification Status ---
app.put("/api/admin/doctors/:id/status", async (req, res) => {
    if (!req.user || req.user.role !== 'admin') {
        return res.status(403).json({ message: "Forbidden: Admin access only" });
    }

    try {
        const { id } = req.params;
        const { status } = req.body;

        if (!['pending', 'verified', 'rejected'].includes(status)) {
            return res.status(400).json({ message: "Invalid status value" });
        }

        const { data: updatedDoctor, error } = await supabase
            .from('doctor_verifications')
            .update({ status })
            .eq('id', id)
            .select()
            .single();

        if (error) throw error;

        if (updatedDoctor && updatedDoctor.user_id) {
            if (status === 'verified') {
                // Update users table, set as verified and make role a doctor
                const { error: userError } = await supabase
                    .from('users')
                    .update({ is_verified: true, role: 'doctor' })
                    .eq('id', updatedDoctor.user_id);
                
                if (userError) throw userError;

                // Safely copy to doctors table
                const { data: existingDoc } = await supabase
                    .from('doctors')
                    .select('id')
                    .eq('user_id', updatedDoctor.user_id)
                    .maybeSingle();
                    
                if (!existingDoc) {
                    const { error: docError } = await supabase.from('doctors').insert({
                        user_id: updatedDoctor.user_id,
                        name: updatedDoctor.full_name,
                        specialization: updatedDoctor.specialty
                    });
                    if (docError) throw docError;
                } else {
                    const { error: docUpdateError } = await supabase.from('doctors')
                        .update({ name: updatedDoctor.full_name, specialization: updatedDoctor.specialty })
                        .eq('user_id', updatedDoctor.user_id);
                    if (docUpdateError) throw docUpdateError;
                }

            } else if (status === 'rejected') {
                // Set is_verified to false explicitly to allow resubmission testing
                const { error: userError } = await supabase
                    .from('users')
                    .update({ is_verified: false })
                    .eq('id', updatedDoctor.user_id);
                
                if (userError) throw userError;
            }
        }

        res.status(200).json({ message: `Doctor ${status}`, doctor: updatedDoctor });
    } catch (err) {
        console.error("Error updating doctor status:", err);
        res.status(500).json({ message: "Server error updating doctor status" });
    }
});

// --- Get Visits Endpoint ---
app.get("/api/visits", async (req, res) => {
    if (!req.user) return res.status(401).json({ message: "Unauthorized" });

    try {
        // Fetch visits with associated ingests
        const { data: visits, error } = await supabase
            .from('visits')
            .select('*, ingests(*)')
            .eq('user_id', req.user.id)
            .order('visit_timestamp', { ascending: false });

        if (error) throw error;

        res.status(200).json(visits);
    } catch (err) {
        console.error("Error fetching visits:", err);
        res.status(500).json({ message: "Server error fetching visits" });
    }
});

// --- Create Visit Endpoint (Handles File Uploads) ---
app.post("/api/visits", upload.array('medicalDocs', 5), async (req, res) => {
    if (!req.user) return res.status(401).json({ message: "Unauthorized" });
    if (!req.user.is_verified) return res.status(403).json({ message: "User not verified" });

    try {
        const { chief_complaint, visit_type, documentTypeMap } = req.body;
        const parsedDocumentTypeMap = JSON.parse(documentTypeMap || '{}');

        if (!chief_complaint) {
            return res.status(400).json({ message: "Chief complaint is required." });
        }

        const visitTimestamp = new Date();
        const bucketName = process.env.SUPABASE_BUCKET_NAME || 'medical-docs';

        // 1. Insert Visit Record
        const { data: visit, error: visitError } = await supabase
            .from('visits')
            .insert({
                user_id: req.user.id,
                pseudonym_id: `P-${req.user.id.slice(-4).toUpperCase()}-${Date.now().toString().slice(-4)}`,
                visit_timestamp: visitTimestamp,
                visit_type: visit_type || 'initial',
                chief_complaint: chief_complaint,
                status: 'requested',
            })
            .select()
            .single();

        if (visitError) throw visitError;

        // 2. Upload Files to Supabase Storage and Insert Ingest Records
        const ingests = [];

        for (const file of req.files) {
            const ingestId = shortUUID.generate();
            const fileType = parsedDocumentTypeMap[file.originalname] || 'clinical_notes';
            const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
            const extension = path.extname(file.originalname);
            const fileName = `${path.basename(file.originalname, extension)}-${uniqueSuffix}${extension}`;
            const supabaseKey = `patients/${req.user.clerk_id}/visits/${visitTimestamp.toISOString().replace(/[:.]/g, '-')}/${fileType}/${fileName}`;

            // Upload via Supabase Storage
            const { data: uploadData, error: uploadError } = await supabase.storage
                .from(bucketName)
                .upload(supabaseKey, file.buffer, {
                    contentType: file.mimetype,
                    upsert: false
                });

            if (uploadError) throw uploadError;

            // Collect record for bulk insert
            ingests.push({
                visit_id: visit.id,
                ingest_id: ingestId,
                type: fileType,
                s3_key: supabaseKey, // Keeping the column name consistent with your previous structure for ease
                s3_bucket: bucketName,
                s3_region: 'supabase',
                original_filename: file.originalname,
                file_size: file.size,
                content_type: file.mimetype
            });
        }

        // 3. Insert Ingest Records into table
        if (ingests.length > 0) {
            const { error: ingestError } = await supabase
                .from('ingests')
                .insert(ingests);

            if (ingestError) {
                console.error("Ingest record error:", ingestError);
                // Optionally handle cleanup of uploaded files here
            }
        }

        // Fetch completed visit with ingests
        const { data: finalVisit } = await supabase
            .from('visits')
            .select('*, ingests(*)')
            .eq('id', visit.id)
            .single();

        res.status(201).json({ message: "Visit requested successfully", visit: finalVisit });

    } catch (err) {
        console.error("Error creating visit:", err);
        if (err instanceof multer.MulterError) {
            return res.status(400).json({ message: `File upload error: ${err.message}` });
        }
        res.status(500).json({ message: "Server error creating visit" });
    }
});

const PORT = process.env.PORT || 5001;
app.listen(PORT, () => console.log(`Supabase Server started on port ${PORT}`));
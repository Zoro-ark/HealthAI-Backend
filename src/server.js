
import express from "express";
import dotenv from "dotenv";
import cors from "cors";
import { connectDB } from "./db.js";
import User from "./models/User.js";
import Visit from "./models/Visit.js";


// --- S3 Imports ---
import { S3Client } from "@aws-sdk/client-s3";
import multer from "multer";
import multerS3 from "multer-s3";
import path from "path";
import shortUUID from "short-uuid"; // For generating ingest_id

dotenv.config();
const app = express();

// --- S3 Client Setup ---
const s3Client = new S3Client({
  region: process.env.AWS_S3_REGION,
  credentials: {
    accessKeyId: process.env.AWS_ACCESS_KEY_ID,
    secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY,
  },
});

const upload = multer({
  storage: multerS3({
    s3: s3Client,
    bucket: process.env.AWS_S3_BUCKET_NAME,
    metadata: function (req, file, cb) {
      cb(null, { fieldName: file.fieldname });
    },
    key: function (req, file, cb) {
      // Construct the S3 key
      const user = req.user; // We'll add user info to req later via middleware
      const visitTimestamp = req.body.visit_timestamp || new Date().toISOString().replace(/[:.]/g, '-'); // Use provided or generate
      const fileType = req.body.documentTypeMap?.[file.originalname] || 'unknown'; // Get type from map sent by frontend
      const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9); // Better uniqueness to be added.
      const extension = path.extname(file.originalname);
      
      // Example Key: patients/user-clerk-id/visits/2025-10-27T14-00-00-000Z/imaging/some-file-1678886400000-123456789.png
      const s3Key = `patients/${user.clerkId}/visits/${visitTimestamp}/${fileType}/${path.basename(file.originalname, extension)}-${uniqueSuffix}${extension}`;
      cb(null, s3Key);
    },
  }),
   limits: { fileSize: 10 * 1024 * 1024 } // Limit file size to 10MB
});
// --- End S3 Setup ---


// CORS configuration
app.use(
  cors({
    origin: "http://localhost:3000", // Frontend API
    methods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allowedHeaders: ["Content-Type", "Authorization"], // Ensure Authorization is allowed if you use Clerk tokens
    credentials: true,
    optionsSuccessStatus: 200,
  })
);

// Other middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true })); // Needed for form data

// --- Simple Middleware to get User from DB based on Clerk ID ---
// Use Clerk's backend SDK for robust authentication (in real app)
const getUserMiddleware = async (req, res, next) => {
    // Assume clerkId is sent in a header or derived from a Clerk token
    // THIS IS SIMPLISTIC - USE CLERK SDK FOR PRODUCTION
    const authHeader = req.headers['authorization']; // Example: Bearer <clerk_id>
    const clerkId = authHeader?.split(' ')[1]; // Highly insecure, just for demo

    if (!clerkId) {
        // If checking status, allow proceeding without user for now
        if (req.path === '/api/user/status' && req.method === 'GET') {
            req.user = null;
            return next();
        }
         if (req.path === '/api/addUser' && req.method === 'POST') {
             return next(); // Allow addUser without this middleware
         }
        return res.status(401).json({ message: 'Unauthorized: No Clerk ID provided' });
    }
    try {
        const user = await User.findOne({ clerkId: clerkId });
        if (!user) {
             if (req.path === '/api/user/status' && req.method === 'GET') {
                req.user = null; // User exists in Clerk but not DB yet
                return next();
            }
            return res.status(404).json({ message: 'User not found in DB' });
        }
        req.user = user; // Attach user object to request
        next();
    } catch (err) {
        console.error("Middleware error:", err);
        res.status(500).json({ message: "Server error in middleware" });
    }
};
app.use('/api', getUserMiddleware); 
// --- End Middleware ---


// Connect Database
connectDB();

// Routes
app.get("/", (req, res) => {
  res.json({ message: "Server running successfully 🚀" });
});

app.post("/api/addUser", async (req, res) => { // Keep this outside middleware or adjust middleware
  try {
    const { clerkId, email, name, role } = req.body;
    console.log("addUser called with:", { clerkId, email, name, role });

    if (!clerkId || !email || !name) {
         return res.status(400).json({ message: "Missing required fields: clerkId, email, name" });
    }


    let user = await User.findOne({ clerkId });
    if (!user) {
      user = new User({ clerkId, email, name, role: role || 'user' }); // Ensure role defaults to user
      await user.save();
      return res.status(201).json({ message: "User created", user });
    }

    console.log("user exists");
    return res.status(200).json({ message: "User already exists", user });
  } catch (err) {
    console.error("Add user error:", err);
     // Check for duplicate key error (if email is unique)
    if (err.code === 11000) {
        return res.status(409).json({ message: "Email already exists" });
    }
    return res.status(500).json({ message: "Server error" });
  }
});

// --- Verification Endpoint ---
app.post("/api/user/verify", async (req, res) => {
    if (!req.user) return res.status(401).json({ message: "Unauthorized" });

    try {
        const { name, age, budget, availabilityDays, visaStatus } = req.body;

        // Basic Validation
        if (!name || !age || !budget || !availabilityDays || !visaStatus ) {
            return res.status(400).json({ message: "Missing verification fields" });
        }

        req.user.name = name; // Update name if provided differently
        req.user.age = parseInt(age, 10);
        req.user.budget = budget;
        req.user.availabilityDays = parseInt(availabilityDays, 10);
        req.user.visaStatus = visaStatus;
        req.user.isVerified = true;

        await req.user.save();

        res.status(200).json({ message: "User verified successfully", user: req.user });

    } catch (err) {
        console.error("Verification error:", err);
        res.status(500).json({ message: "Server error during verification" });
    }
});

// --- User Status Endpoint ---
app.get("/api/user/status", (req, res) => {
    // Middleware attaches req.user if found
    if (req.user) {
        res.status(200).json({
            isVerified: req.user.isVerified || false,
            clerkId: req.user.clerkId,
             userId: req.user._id // Send MongoDB ID too
            // Add other details if needed by frontend
        });
    } else {
         // If middleware didn't find user (even if clerkId was sent), means not in DB
         // Or if no clerkId sent at all.
        res.status(200).json({ isVerified: false, clerkId: null, userId: null });
    }
});


// --- Get Visits Endpoint ---
app.get("/api/visits", async (req, res) => {
    if (!req.user) return res.status(401).json({ message: "Unauthorized" });

    try {
        const visits = await Visit.find({ user: req.user._id }).sort({ visit_timestamp: -1 }); // Sort by most recent
        res.status(200).json(visits);
    } catch (err) {
        console.error("Error fetching visits:", err);
        res.status(500).json({ message: "Server error fetching visits" });
    }
});


// --- Create Visit Endpoint (Handles File Uploads) ---
// Use upload.array('medicalDocs', 5) to accept up to 5 files with field name 'medicalDocs' (upload is present in multer)
app.post("/api/visits", upload.array('medicalDocs', 5), async (req, res) => {
    if (!req.user) return res.status(401).json({ message: "Unauthorized" });
    if (!req.user.isVerified) return res.status(403).json({ message: "User not verified" });

    try {
        const { chief_complaint, visit_type, documentTypeMap } = req.body;
         const parsedDocumentTypeMap = JSON.parse(documentTypeMap || '{}'); // Frontend sends map of originalFilename -> type

        if (!chief_complaint) {
            return res.status(400).json({ message: "Chief complaint is required." });
        }

         const visitTimestamp = new Date(); // Use server time for consistency

        // Create ingest data from uploaded files (req.files is populated by multer-s3)
        const ingests = req.files.map(file => ({
            ingest_id: shortUUID.generate(), // Generate a unique ID
            type: parsedDocumentTypeMap[file.originalname] || 'clinical_notes', // Get type from map, default if needed
            s3_key: file.key, // Key provided by multer-s3
            s3_bucket: file.bucket, // Bucket provided by multer-s3
            s3_region: process.env.AWS_S3_REGION,
            upload_timestamp: new Date(),
            original_filename: file.originalname,
            file_size: file.size,
            content_type: file.contentType,
        }));

        const newVisit = new Visit({
            user: req.user._id,
            pseudonym_id: `P-${req.user._id.toString().slice(-4).toUpperCase()}-${Date.now().toString().slice(-4)}`, // Example pseudonym
            visit_timestamp: visitTimestamp,
            visit_type: visit_type || 'initial', // Default or from form
            chief_complaint: chief_complaint,
            ingests: ingests,
            status: 'requested', // Initial status
        });

        await newVisit.save();

        res.status(201).json({ message: "Visit requested successfully", visit: newVisit });

    } catch (err) {
        console.error("Error creating visit:", err);
         if (err instanceof multer.MulterError) {
             return res.status(400).json({ message: `File upload error: ${err.message}` });
         }
        res.status(500).json({ message: "Server error creating visit" });
    }
});


// Start Server
const PORT = process.env.PORT || 5001;
app.listen(PORT, () => console.log(`Server started on port ${PORT}`)); //
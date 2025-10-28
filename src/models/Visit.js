import mongoose from "mongoose";

const ingestSchema = new mongoose.Schema({
  ingest_id: { type: String, required: true, unique: true }, // Change to mongoose ObjectId or UUID later
  type: {
    type: String,
    enum: ["prescription", "lab_report", "imaging", "clinical_notes"],
    required: true,
  },
  s3_key: { type: String, required: true },
  s3_bucket: { type: String, required: true },
  s3_region: { type: String, required: true },
  upload_timestamp: { type: Date, default: Date.now },
  original_filename: { type: String },
  file_size: { type: Number },
  content_type: { type: String },
  // processing_status, parsed_text, structured_data to be added later
});

const visitSchema = new mongoose.Schema(
  {
    user: { type: mongoose.Schema.Types.ObjectId, ref: "User", required: true }, // Link to the user
    pseudonym_id: { type: String, required: true }, // link this to User or Patient model 
    visit_timestamp: { type: Date, default: Date.now, required: true },
    visit_type: {
      type: String,
      enum: ["initial", "follow_up", "emergency", "routine_checkup"],
      default: "initial"
    },
    chief_complaint: { type: String },
    ingests: [ingestSchema],
    status: {
      type: String,
      enum: ["in_progress", "completed", "cancelled", "requested"], 
      default: "requested",
    },
    // outputs, visit_summary, doctor_notes, clinician_id, human_review_completed  to be added later
  },
  { timestamps: true } // Adds createdAt and updatedAt automatically
);

// Ensure visits are sorted by timestamp when fetched if needed, or handle in query
// visitSchema.index({ user: 1, visit_timestamp: -1 });

export default mongoose.model("Visit", visitSchema);
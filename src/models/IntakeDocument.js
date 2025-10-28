import mongoose from "mongoose";

// not using this, instead using ingestSchema right now.
const intakeDocumentSchema = new mongoose.Schema(
  {
    pseudonymId: { type: String, required: true },
    originalFilename: { type: String, required: true },
    fileType: {
      type: String,
      enum: ["prescription", "lab_report", "imaging", "clinical_notes"],
      required: true,
    },
    s3Key: { type: String, required: true },
    s3Bucket: { type: String, required: true },
    s3Region: { type: String, required: true },
    url: { type: String },
    fileSize: { type: Number },
  },
  { timestamps: true }
);

export default mongoose.model("IntakeDocument", intakeDocumentSchema);

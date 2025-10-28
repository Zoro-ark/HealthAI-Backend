import mongoose from "mongoose";

const patientSchema = new mongoose.Schema(
  {
    pseudonymId: { type: String, required: true, unique: true },
    user: { type: mongoose.Schema.Types.ObjectId, ref: "User" },
    createdAt: { type: Date, default: Date.now },
  },
  { timestamps: true }
);

export default mongoose.model("Patient", patientSchema);

import mongoose from "mongoose";

const userSchema = new mongoose.Schema(
  {
    name: { type: String, required: true, trim: true },
    email: { type: String, required: true, unique: true, lowercase: true },
    password: { type: String, default: null },
    clerkId: { type: String, required: true, unique: true },
    role: { type: String, enum: ["user", "doctor", "admin"], default: "user" },
  

  // --- Verification Fields ---
  isVerified: { type: Boolean, default: false },
  age: { type: Number },
  budget: { type: String }, // May change to number later
  availabilityDays: { type: Number },
  visaStatus: { type: String, enum: ["indian_citizen", "not_indian_citizen", "other"] },
  // --- End of Verification fields --- 
  
  },
  { timestamps: true }
  
);

export default mongoose.model("User", userSchema);

import mongoose from "mongoose";

const s3ConfigSchema = new mongoose.Schema(
  {
    bucket: String,
    region: String,
    accessKey: String,
    secretKey: String,
  },
  { timestamps: true }
);

export default mongoose.model("S3Config", s3ConfigSchema);

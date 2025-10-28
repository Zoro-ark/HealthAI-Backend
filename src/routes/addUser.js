import express from "express";
const router = express.Router();

router.post("/addUser", async (req, res) => {
  console.log("addUser called");
  res.json({ message: "User added successfully!" });
});

export default router;

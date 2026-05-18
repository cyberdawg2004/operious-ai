const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export async function getHealth() {
  const response = await fetch(`${API_URL}/api/v1/health`);

  if (!response.ok) {
    throw new Error("Failed to fetch health status");
  }

  return response.json();
}

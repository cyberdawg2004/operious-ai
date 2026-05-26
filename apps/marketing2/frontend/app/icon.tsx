export const contentType = "image/svg+xml";

export default function Icon() {
  return new Response(
    `<svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" fill="#05080F"/>
      <polygon points="16,2 28,9 28,23 16,30 4,23 4,9" stroke="#A8882C" stroke-width="1.5" fill="none"/>
      <polygon points="16,8 22,11.5 22,18.5 16,22 10,18.5 10,11.5" stroke="#2A5CAA" stroke-width="1" fill="none"/>
      <circle cx="16" cy="15" r="1.5" fill="#A8882C"/>
    </svg>`,
    {
      headers: {
        "Content-Type": contentType,
      },
    }
  );
}

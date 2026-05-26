import { ImageResponse } from "next/og";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          background: "#050505",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <svg
          width="28"
          height="28"
          viewBox="0 0 32 32"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <polygon
            points="16,2 28,9 28,23 16,30 4,23 4,9"
            stroke="#C9A84C"
            strokeWidth="1.6"
            fill="none"
          />
          <polygon
            points="16,8 22,11.5 22,18.5 16,22 10,18.5 10,11.5"
            stroke="#2A5CAA"
            strokeWidth="1.1"
            fill="none"
          />
          <line x1="16" y1="2" x2="16" y2="8" stroke="#C9A84C" strokeWidth="1.6" />
          <line
            x1="28"
            y1="23"
            x2="22"
            y2="18.5"
            stroke="#C9A84C"
            strokeWidth="1.6"
          />
          <line x1="4" y1="23" x2="10" y2="18.5" stroke="#C9A84C" strokeWidth="1.6" />
          <circle cx="16" cy="15" r="1.6" fill="#C9A84C" />
        </svg>
      </div>
    ),
    { ...size }
  );
}

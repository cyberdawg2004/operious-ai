import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sign In | Operious Command Center",
  description: "Secure authentication for Operious AI Command Center - Governed Operational Intelligence",
};

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      {/* Hide the navigation by positioning over it */}
      <style>{`
        nav { display: none !important; }
        body { background-color: #0A0A0C !important; }
      `}</style>
      <div 
        className="fixed inset-0 flex items-center justify-center"
        style={{ backgroundColor: "#0A0A0C" }}
      >
        {children}
      </div>
    </>
  );
}

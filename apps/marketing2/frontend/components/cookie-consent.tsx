"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";

const COOKIE_CONSENT_KEY = "operious_cookie_consent";

type ConsentState = {
  essential: boolean;
  analytics: boolean;
  marketing: boolean;
};

export function CookieConsent() {
  const [isVisible, setIsVisible] = useState(false);
  const [showPreferences, setShowPreferences] = useState(false);
  const [consent, setConsent] = useState<ConsentState>({
    essential: true,
    analytics: false,
    marketing: false,
  });

  useEffect(() => {
    // Check if user has already consented
    const savedConsent = localStorage.getItem(COOKIE_CONSENT_KEY);
    if (!savedConsent) {
      // Small delay before showing banner for better UX
      const timer = setTimeout(() => setIsVisible(true), 1000);
      return () => clearTimeout(timer);
    }
  }, []);

  const saveConsent = (consentState: ConsentState) => {
    localStorage.setItem(COOKIE_CONSENT_KEY, JSON.stringify(consentState));
    setIsVisible(false);
  };

  const handleAcceptAll = () => {
    const fullConsent = { essential: true, analytics: true, marketing: true };
    setConsent(fullConsent);
    saveConsent(fullConsent);
  };

  const handleAcceptEssential = () => {
    const essentialOnly = { essential: true, analytics: false, marketing: false };
    setConsent(essentialOnly);
    saveConsent(essentialOnly);
  };

  const handleSavePreferences = () => {
    saveConsent(consent);
  };

  const toggleConsent = (key: keyof ConsentState) => {
    if (key === "essential") return; // Essential cannot be toggled
    setConsent((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          initial={{ y: 100, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 100, opacity: 0 }}
          transition={{ duration: 0.3, ease: "easeOut" }}
          className="fixed bottom-0 left-0 right-0 z-50 p-4 sm:p-6"
        >
          <div
            className="max-w-[800px] mx-auto rounded-[4px] p-6 sm:p-8"
            style={{
              backgroundColor: "var(--cc-bg-surface)",
              border: "1px solid var(--cc-border-subtle)",
              boxShadow: "0 -8px 32px rgba(0, 0, 0, 0.4)",
            }}
          >
            {/* Header */}
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3
                  className="text-[18px] font-semibold"
                  style={{
                    fontFamily: "var(--font-cormorant-sc)",
                    color: "var(--cc-text-primary)",
                  }}
                >
                  Cookie Preferences
                </h3>
                <p
                  className="mt-1 text-[11px] uppercase tracking-[0.12em]"
                  style={{
                    fontFamily: "var(--font-ibm-plex-mono)",
                    color: "var(--cc-text-muted)",
                  }}
                >
                  Data Governance Notice
                </p>
              </div>
              <button
                onClick={handleAcceptEssential}
                className="flex h-11 w-11 items-center justify-center rounded-[4px] transition-colors duration-150 hover:bg-[var(--cc-bg-raised)]"
                aria-label="Close cookie banner"
              >
                <X size={18} style={{ color: "var(--cc-text-muted)" }} />
              </button>
            </div>

            {/* Description */}
            <p
              className="text-[14px] leading-[1.6] mb-6"
              style={{
                fontFamily: "var(--font-geist-sans)",
                color: "var(--cc-text-secondary)",
              }}
            >
              Operious uses cookies to ensure operational continuity and improve platform
              performance. Essential cookies are required for core functionality. Analytics and
              marketing cookies are optional.
            </p>

            {/* Preferences Panel */}
            <AnimatePresence>
              {showPreferences && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="overflow-hidden mb-6"
                >
                  <div
                    className="p-4 rounded-[4px] space-y-4"
                    style={{
                      backgroundColor: "var(--cc-bg-raised)",
                      border: "1px solid var(--cc-border-subtle)",
                    }}
                  >
                    {/* Essential Cookies */}
                    <CookieToggle
                      label="Essential Cookies"
                      description="Required for authentication, security, and core platform operations."
                      checked={consent.essential}
                      disabled
                      onChange={() => {}}
                    />

                    {/* Analytics Cookies */}
                    <CookieToggle
                      label="Analytics Cookies"
                      description="Help us understand platform usage and improve performance."
                      checked={consent.analytics}
                      onChange={() => toggleConsent("analytics")}
                    />

                    {/* Marketing Cookies */}
                    <CookieToggle
                      label="Marketing Cookies"
                      description="Used to deliver relevant enterprise communications."
                      checked={consent.marketing}
                      onChange={() => toggleConsent("marketing")}
                    />
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Actions */}
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
              {/* Manage Preferences Toggle */}
              <button
                onClick={() => setShowPreferences(!showPreferences)}
                className="h-11 px-4 rounded-[4px] text-[13px] font-medium transition-colors duration-150 sm:h-10"
                style={{
                  fontFamily: "var(--font-geist-sans)",
                  backgroundColor: "transparent",
                  border: "1px solid var(--cc-border-subtle)",
                  color: "var(--cc-text-secondary)",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "var(--cc-gold-primary)";
                  e.currentTarget.style.color = "var(--cc-text-primary)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "var(--cc-border-subtle)";
                  e.currentTarget.style.color = "var(--cc-text-secondary)";
                }}
              >
                {showPreferences ? "Hide Preferences" : "Manage Preferences"}
              </button>

              <div className="flex-1" />

              {/* Accept Essential */}
              <button
                onClick={showPreferences ? handleSavePreferences : handleAcceptEssential}
                className="h-11 px-4 rounded-[4px] text-[13px] font-medium transition-colors duration-150 sm:h-10"
                style={{
                  fontFamily: "var(--font-geist-sans)",
                  backgroundColor: "transparent",
                  border: "1px solid var(--cc-border-subtle)",
                  color: "var(--cc-text-secondary)",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "var(--cc-gold-primary)";
                  e.currentTarget.style.color = "var(--cc-text-primary)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "var(--cc-border-subtle)";
                  e.currentTarget.style.color = "var(--cc-text-secondary)";
                }}
              >
                {showPreferences ? "Save Preferences" : "Essential Only"}
              </button>

              {/* Accept All */}
              <button
                onClick={handleAcceptAll}
                className="h-11 px-6 rounded-[4px] text-[13px] font-semibold transition-colors duration-150 sm:h-10"
                style={{
                  fontFamily: "var(--font-cormorant-sc)",
                  backgroundColor: "var(--cc-gold-primary)",
                  color: "var(--cc-bg-deep)",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = "var(--cc-gold-hover)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = "var(--cc-gold-primary)";
                }}
              >
                Accept All
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// Cookie Toggle Component
function CookieToggle({
  label,
  description,
  checked,
  disabled = false,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  onChange: () => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex-1">
        <p
          className="text-[14px] font-medium"
          style={{
            fontFamily: "var(--font-geist-sans)",
            color: "var(--cc-text-primary)",
          }}
        >
          {label}
          {disabled && (
            <span
              className="ml-2 text-[10px] uppercase tracking-wider"
              style={{
                fontFamily: "var(--font-ibm-plex-mono)",
                color: "var(--cc-text-muted)",
              }}
            >
              Required
            </span>
          )}
        </p>
        <p
          className="mt-1 text-[12px]"
          style={{
            fontFamily: "var(--font-geist-sans)",
            color: "var(--cc-text-muted)",
          }}
        >
          {description}
        </p>
      </div>
      <button
        onClick={onChange}
        disabled={disabled}
        className="relative flex h-11 w-12 flex-shrink-0 items-center rounded-full transition-colors duration-150"
        style={{
          backgroundColor: checked ? "var(--cc-gold-primary)" : "var(--cc-border-subtle)",
          opacity: disabled ? 0.5 : 1,
          cursor: disabled ? "not-allowed" : "pointer",
        }}
        aria-checked={checked}
        role="switch"
      >
        <span
          className="absolute top-1/2 h-5 w-5 rounded-full transition-transform duration-150"
          style={{
            backgroundColor: "var(--cc-text-primary)",
            transform: checked ? "translate(22px, -50%)" : "translate(4px, -50%)",
          }}
        />
      </button>
    </div>
  );
}

import * as LucideIcons from "lucide-react";
import type { LucideIcon, LucideProps } from "lucide-react";
import type { ComponentType } from "react";

export interface CommandIconOption {
  name: string;
  label: string;
  category: string;
}

export const POPULAR_COMMAND_ICONS: CommandIconOption[] = [
  // General & System
  { name: "Terminal", label: "Terminal", category: "System" },
  { name: "Activity", label: "Activity", category: "System" },
  { name: "Cpu", label: "CPU", category: "System" },
  { name: "Settings", label: "Settings", category: "System" },
  { name: "Power", label: "Power", category: "System" },
  { name: "Sparkles", label: "Sparkles", category: "General" },

  // Communication & Organization
  { name: "Bell", label: "Reminder / Alarm", category: "Alerts" },
  { name: "Mail", label: "Email", category: "Communication" },
  { name: "MessageSquare", label: "Message", category: "Communication" },
  { name: "Phone", label: "Phone", category: "Communication" },
  { name: "Calendar", label: "Calendar", category: "Organization" },
  { name: "Clock", label: "Clock", category: "Organization" },
  { name: "Search", label: "Search", category: "General" },

  // Media & Weather
  { name: "Music2", label: "Music", category: "Media" },
  { name: "Volume2", label: "Volume Up", category: "Media" },
  { name: "VolumeX", label: "Mute", category: "Media" },
  { name: "Play", label: "Play", category: "Media" },
  { name: "Tv", label: "TV", category: "Media" },
  { name: "CloudSun", label: "Weather", category: "Weather" },
  { name: "Sun", label: "Sun", category: "Weather" },
  { name: "Moon", label: "Moon", category: "Weather" },

  // Smart Home & Security
  { name: "DoorOpen", label: "Door", category: "Smart Home" },
  { name: "Home", label: "Home", category: "Smart Home" },
  { name: "Lightbulb", label: "Light", category: "Smart Home" },
  { name: "Lock", label: "Lock", category: "Security" },
  { name: "Unlock", label: "Unlock", category: "Security" },
  { name: "Shield", label: "Shield", category: "Security" },
  { name: "ShieldAlert", label: "Shield Alert", category: "Security" },
  { name: "Key", label: "Key", category: "Security" },
  { name: "Camera", label: "Camera", category: "Security" },
  { name: "Wifi", label: "WiFi", category: "Network" },
];

/**
 * Safely resolves a Lucide icon component by name.
 * Accepts PascalCase ("CloudSun"), kebab-case ("cloud-sun"), snake_case ("cloud_sun"),
 * or lower-case names, falling back to `Terminal` if the icon is not found.
 */
export function getLucideIcon(iconName?: string | null): LucideIcon {
  if (!iconName || typeof iconName !== "string") {
    return LucideIcons.Terminal;
  }

  const iconsMap = LucideIcons as unknown as Record<
    string,
    ComponentType<LucideProps> | undefined
  >;

  // Direct lookup (e.g. "Terminal", "CloudSun")
  const directMatch = iconsMap[iconName];
  if (
    (directMatch && typeof directMatch === "object") ||
    typeof directMatch === "function"
  ) {
    return directMatch as LucideIcon;
  }

  // Convert kebab-case, snake_case, or lowercase to PascalCase
  const pascalCase = iconName
    .trim()
    .split(/[-_ ]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join("");

  const pascalMatch = iconsMap[pascalCase];
  if (
    pascalMatch &&
    (typeof pascalMatch === "object" || typeof pascalMatch === "function")
  ) {
    return pascalMatch as LucideIcon;
  }

  // Case-insensitive fallback lookup
  const lowerTarget = iconName.toLowerCase().replace(/[-_ ]/g, "");
  for (const key of Object.keys(iconsMap)) {
    if (key.toLowerCase() === lowerTarget) {
      const match = iconsMap[key];
      if (match && (typeof match === "object" || typeof match === "function")) {
        return match as LucideIcon;
      }
    }
  }

  return LucideIcons.Terminal;
}

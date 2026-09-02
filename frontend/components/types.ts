import type { LucideIcon } from "lucide-react";

export interface VoiceCommand {
  id: string;
  intent?: string;
  label: string;
  description: string;
  icon: string | LucideIcon;
  important: boolean;
}

export interface WeatherSnapshot {
  location: string;
  tempC: number;
  feelsLikeC: number;
  condition: string;
  humidityPct: number;
  windKph: number;
}

import type { LucideIcon } from "lucide-react";

export interface VoiceCommand {
  id: string;
  label: string;
  description: string;
  icon: LucideIcon;
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

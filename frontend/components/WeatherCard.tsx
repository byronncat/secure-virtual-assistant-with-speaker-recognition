import { CloudSun } from "lucide-react";
import clsx from "clsx";
import type { WeatherSnapshot } from "./types";

interface WeatherCardProps {
  data: WeatherSnapshot;
}

export default function WeatherCard({ data }: WeatherCardProps) {
  return (
    <div
      className={clsx(
        "flex items-center justify-between gap-4",
        "rounded-2xl border border-white/12",
        "bg-background px-5 py-4",
      )}
    >
      <div className="flex items-center gap-3">
        <CloudSun size={30} strokeWidth={1.5} className="text-normal" />
        <div>
          <p className="text-[26px] text-normal">{data.tempC}°C</p>
          <p className="mt-1 text-[13px] text-faint">{data.condition}</p>
        </div>
      </div>
      <div className="space-y-1 text-right text-[12.5px] text-normal">
        <p>Feels like {data.feelsLikeC}°C</p>
        <p>Humidity {data.humidityPct}%</p>
        <p>Wind {data.windKph} km/h</p>
      </div>
    </div>
  );
}

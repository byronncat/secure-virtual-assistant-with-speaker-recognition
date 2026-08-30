import type { WeatherSnapshot } from "./types";

import clsx from "clsx";
import { Sparkles, Undo2 } from "lucide-react";
import WeatherCard from "./WeatherCard";
import MessageActions from "./MessageActions";

const WEATHER: WeatherSnapshot = {
  location: "Ho Chi Minh City",
  tempC: 32,
  feelsLikeC: 36,
  condition: "Partly cloudy",
  humidityPct: 62,
  windKph: 12,
};

export default function RightSidebar() {
  return (
    <aside className="size-full p-4 min-h-0">
      <div
        className={clsx(
          "bg-card size-full",
          "flex flex-col",
          "rounded-xl border border-white/12",
        )}
      >
        <Header />
        <Conversation />
        <Composer />
      </div>
    </aside>
  );
}

function Header() {
  return (
    <div
      className={clsx(
        "flex items-center gap-2",
        "border-b border-white/12",
        "p-4 text-primary",
      )}
    >
      <Sparkles size={18} className="text-accent" strokeWidth={1.75} />
      <h2 className="text-[15px] font-medium text-ink">
        Assistant&apos;s Response
      </h2>
    </div>
  );
}

function Conversation() {
  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className={clsx("flex flex-col gap-5", "text-[16px] text-normal")}>
        <p>Sure! Here&apos;s the current weather in {WEATHER.location}:</p>

        <WeatherCard data={WEATHER} />

        <p>
          It looks warm with a chance of scattered thunderstorms in the
          afternoon. Don&apos;t forget to stay hydrated!
        </p>

        <p>Would you like me to check anything else for you?</p>

        <p>
          Lorem ipsum dolor sit amet, consectetur adipiscing elit. Mauris tortor
          tellus, tristique in faucibus non, convallis id turpis. Proin pulvinar
          blandit tellus sed porta. Vivamus viverra porta posuere. Nunc vehicula
          vulputate dui, vitae volutpat quam faucibus a. In venenatis arcu
          lobortis justo pretium, non dictum nibh ultrices. Curabitur ultrices
          arcu magna, nec efficitur lectus ullamcorper ac. Curabitur quis leo
          dui. Etiam dui libero, feugiat ut venenatis a, molestie a tellus.
          Etiam feugiat mauris leo, eu hendrerit leo bibendum vel. Integer eros
          augue, tristique sit amet interdum eu, convallis vel nunc.
        </p>

        <p>
          Lorem ipsum dolor sit amet, consectetur adipiscing elit. Mauris et
          ornare urna. Nam imperdiet dignissim lorem, sed sodales augue. Integer
          at blandit nisi, eget interdum erat. Etiam turpis lorem, luctus eu
          commodo id, aliquet rutrum metus. Fusce at rutrum erat. In nec
          molestie mi, eu mattis sapien. Curabitur fringilla diam non velit
          laoreet dictum. Phasellus blandit, nisi sollicitudin sollicitudin
          molestie, ex lectus consequat tellus, vel dignissim est ipsum sed
          ipsum.
        </p>

        <MessageActions />
      </div>
    </div>
  );
}

function Composer() {
  return (
    <div className="border-t border-white/12 p-4">
      <div
        className={clsx(
          "flex items-center gap-2",
          "rounded-full border border-white/12 bg-background",
          "py-1 pl-5 pr-1.5",
        )}
      >
        <input
          type="text"
          placeholder="Ask me anything..."
          className={clsx(
            "flex-1 bg-transparent py-2.5",
            "text-[14px] text-normal",
            "placeholder:text-faint focus:outline-none",
          )}
        />
        <button
          type="button"
          aria-label="Send message"
          className={clsx(
            "flex size-9 shrink-0 items-center justify-center",
            "rounded-full",
            "hover:bg-white/10 text-normal/80 hover:text-normal",
            "transition-colors ease-in-out duration-200 cursor-pointer",
          )}
        >
          <Undo2 size={17} strokeWidth={2} />
        </button>
      </div>
    </div>
  );
}

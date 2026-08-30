import clsx from "clsx";
import LeftSidebar from "@/components/LeftSidebar";
import CenterPanel from "@/components/CenterPanel";
import RightSidebar from "@/components/RightSidebar";

export default function Home() {
  return (
    <main
      className={clsx(
        "grid h-screen grid-cols-[300px_1fr_380px]",
        "overflow-hidden bg-background text-normal",
      )}
    >
      <LeftSidebar />
      <CenterPanel />
      <RightSidebar />
    </main>
  );
}

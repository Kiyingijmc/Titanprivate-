import { describe, it, expect } from "vitest";
import { deriveConnection } from "./connection";

describe("deriveConnection", () => {
  it("connecting before first WS open", () => {
    expect(deriveConnection({ wsConnected: false, everConnected: false, reconnecting: false, pollOk: false, lastHeartbeatAgeS: null }).status).toBe("connecting");
  });
  it("live when WS connected", () => {
    expect(deriveConnection({ wsConnected: true, everConnected: true, reconnecting: false, pollOk: true, lastHeartbeatAgeS: 2 }).status).toBe("live");
  });
  it("reconnecting when WS dropped and backing off (no poll yet)", () => {
    expect(deriveConnection({ wsConnected: false, everConnected: true, reconnecting: true, pollOk: false, lastHeartbeatAgeS: 5 }).status).toBe("reconnecting");
  });
  it("degraded when WS down but polling returns snapshots", () => {
    expect(deriveConnection({ wsConnected: false, everConnected: true, reconnecting: true, pollOk: true, lastHeartbeatAgeS: 5 }).status).toBe("degraded");
  });
  it("offline when WS down and polling failing after having connected", () => {
    expect(deriveConnection({ wsConnected: false, everConnected: true, reconnecting: false, pollOk: false, lastHeartbeatAgeS: 5 }).status).toBe("offline");
  });
  it("stale is orthogonal — live but heartbeat old", () => {
    const s = deriveConnection({ wsConnected: true, everConnected: true, reconnecting: false, pollOk: true, lastHeartbeatAgeS: 120 });
    expect(s.status).toBe("live");
    expect(s.stale).toBe(true);
  });
  it("not stale within threshold", () => {
    expect(deriveConnection({ wsConnected: true, everConnected: true, reconnecting: false, pollOk: true, lastHeartbeatAgeS: 10 }).stale).toBe(false);
  });
});

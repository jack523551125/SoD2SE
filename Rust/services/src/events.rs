//! Value-only owned events and background timer notifications. No engine-thread claim.
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sod2se_abi::{INVALID, STALE};
use std::collections::{BTreeMap, VecDeque};
#[derive(Clone, Serialize, Deserialize)]
pub struct Event {
    pub sequence: u64,
    pub id: String,
    pub owner: u64,
    pub data: Value,
}
#[derive(Default)]
pub struct Events {
    sequence: u64,
    records: VecDeque<Event>,
    subscriptions: BTreeMap<u64, String>,
    next: u64,
}
impl Events {
    pub fn subscribe(&mut self, owner: u64, prefix: String) -> Result<u64, i32> {
        if owner == 0 || prefix.is_empty() || prefix.len() > 128 || self.subscriptions.len() >= 256
        {
            return Err(INVALID);
        }
        self.next = self.next.checked_add(1).ok_or(STALE)?;
        self.subscriptions.insert(self.next, prefix);
        Ok(self.next)
    }
    pub fn publish(&mut self, owner: u64, id: String, data: Value) -> Result<u64, i32> {
        if id.is_empty() || id.len() > 128 || data.to_string().len() > 8192 {
            return Err(INVALID);
        }
        self.sequence = self.sequence.checked_add(1).ok_or(STALE)?;
        self.records.push_back(Event {
            sequence: self.sequence,
            id,
            owner,
            data,
        });
        if self.records.len() > 1024 {
            self.records.pop_front();
        }
        Ok(self.sequence)
    }
    pub fn poll(&self, subscription: u64, since: u64) -> Result<(u64, Vec<Event>), i32> {
        let prefix = self.subscriptions.get(&subscription).ok_or(INVALID)?;
        if since > self.sequence
            || self
                .records
                .front()
                .is_some_and(|e| since < e.sequence.saturating_sub(1))
        {
            return Err(STALE);
        }
        let records: Vec<_> = self
            .records
            .iter()
            .filter(|e| e.sequence > since && e.id.starts_with(prefix))
            .take(64)
            .cloned()
            .collect();
        let cursor = if records.len() == 64 {
            records.last().unwrap().sequence
        } else {
            self.sequence
        };
        Ok((cursor, records))
    }
    pub fn remove(&mut self, subscription: u64) {
        self.subscriptions.remove(&subscription);
    }
}
struct Timer {
    owner: u64,
    due: u64,
    repeat: Option<u64>,
}
#[derive(Default)]
pub struct Scheduler {
    next: u64,
    timers: BTreeMap<u64, Timer>,
}
impl Scheduler {
    pub fn schedule(
        &mut self,
        owner: u64,
        now: u64,
        delay: u64,
        repeat: Option<u64>,
    ) -> Result<u64, i32> {
        if owner == 0
            || delay == 0
            || delay > 600000
            || repeat.is_some_and(|n| n == 0 || n > 600000)
            || self.timers.len() >= 256
        {
            return Err(INVALID);
        }
        self.next = self.next.checked_add(1).ok_or(STALE)?;
        self.timers.insert(
            self.next,
            Timer {
                owner,
                due: now.checked_add(delay).ok_or(STALE)?,
                repeat,
            },
        );
        Ok(self.next)
    }
    pub fn cancel(&mut self, owner: u64, id: u64) -> Result<(), i32> {
        if self.timers.get(&id).map(|t| t.owner) != Some(owner) {
            return Err(INVALID);
        }
        self.timers.remove(&id);
        Ok(())
    }
    pub fn unregister(&mut self, owner: u64) {
        self.timers.retain(|_, t| t.owner != owner);
    }
    pub fn tick(&mut self, now: u64, events: &mut Events) {
        let due: Vec<_> = self
            .timers
            .iter()
            .filter(|(_, t)| t.due <= now)
            .map(|(&id, t)| (id, t.owner, t.repeat))
            .collect();
        for (id, owner, repeat) in due {
            let _ = events.publish(owner, "task.due".into(), json!({"id":id}));
            if let Some(repeat) = repeat {
                if let Some(due) = now.checked_add(repeat) {
                    self.timers.get_mut(&id).unwrap().due = due;
                } else {
                    self.timers.remove(&id);
                }
            } else {
                self.timers.remove(&id);
            }
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn timer_ownership_and_cleanup() {
        let mut events = Events::default();
        let subscription = events.subscribe(1, "task.".into()).unwrap();
        let mut scheduler = Scheduler::default();
        let timer = scheduler.schedule(1, 0, 10, None).unwrap();
        assert!(scheduler.cancel(2, timer).is_err());
        scheduler.tick(9, &mut events);
        assert!(events.poll(subscription, 0).unwrap().1.is_empty());
        scheduler.tick(10, &mut events);
        assert_eq!(events.poll(subscription, 0).unwrap().1.len(), 1);
        scheduler.schedule(1, 10, 10, None).unwrap();
        scheduler.unregister(1);
        scheduler.tick(100, &mut events);
        assert_eq!(events.poll(subscription, 0).unwrap().1.len(), 1);
    }
    #[test]
    fn bounded_event_cursors() {
        let mut events = Events::default();
        let subscription = events.subscribe(1, "example.".into()).unwrap();
        for _ in 0..1025 {
            events
                .publish(1, "example.ready".into(), json!({}))
                .unwrap();
        }
        assert!(matches!(events.poll(subscription, 0), Err(STALE)));
        assert_eq!(events.poll(subscription, 1).unwrap().1.len(), 64);
        events.remove(subscription);
        assert!(events.poll(subscription, 1025).is_err());
    }
}

//! Value-only follower persistence policy. Native pointers never enter this document.
use serde::{Deserialize, Serialize};
use sod2se_abi::{INVALID, UNSUPPORTED};
use std::collections::{BTreeMap, BTreeSet};

pub const MAX_FOLLOWERS: usize = 512;
pub const MAX_COMMUNITIES: usize = 64;

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Identity {
    pub id: i32,
    pub narrative: u64,
    pub entity: u64,
}
impl Identity {
    pub fn validate(&self) -> Result<(), i32> {
        // Ordinary community members can have no narrative binding. Preserve
        // both zero fields exactly; the original numeric ID and community
        // GameId still identify their saved record. The default ID is invalid.
        if self.id < 0 {
            return Err(INVALID);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Document {
    pub format: u32,
    pub communities: BTreeMap<String, Vec<Identity>>,
}
impl Default for Document {
    fn default() -> Self {
        Self {
            format: 1,
            communities: BTreeMap::new(),
        }
    }
}
fn valid_key(key: &str) -> bool {
    key.len() == 32
        && key
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        && key.bytes().any(|b| b != b'0')
}
fn roster(values: &[Identity]) -> Result<BTreeSet<Identity>, i32> {
    if values.len() > MAX_FOLLOWERS {
        return Err(INVALID);
    }
    let mut ids = BTreeSet::new();
    let mut result = BTreeSet::new();
    for value in values {
        value.validate()?;
        if !ids.insert(value.id) {
            return Err(INVALID);
        }
        result.insert(value.clone());
    }
    Ok(result)
}
impl Document {
    pub fn validate(&self) -> Result<(), i32> {
        if self.format != 1 {
            return Err(UNSUPPORTED);
        }
        if self.communities.len() > MAX_COMMUNITIES {
            return Err(INVALID);
        }
        for (key, values) in &self.communities {
            if !valid_key(key) {
                return Err(INVALID);
            }
            roster(values)?;
        }
        Ok(())
    }
}

struct Session {
    key: String,
    epoch: u64,
    desired: BTreeSet<Identity>,
    live: BTreeSet<Identity>,
}
pub struct Policy {
    document: Document,
    session: Option<Session>,
    dirty: bool,
}
impl Policy {
    pub fn new(document: Document) -> Result<Self, i32> {
        document.validate()?;
        Ok(Self {
            document,
            session: None,
            dirty: false,
        })
    }
    /// Only a qualified native snapshot may enter here. Missing/loading worlds call leave.
    /// Absence is never interpreted as explicit dismissal, death or a completed restore.
    pub fn observe(&mut self, key: &str, epoch: u64, live: &[Identity]) -> Result<(), i32> {
        if !valid_key(key) || epoch == 0 {
            return Err(INVALID);
        }
        let live = roster(live)?;
        if !self.document.communities.contains_key(key)
            && self.document.communities.len() == MAX_COMMUNITIES
        {
            return Err(INVALID);
        }
        let new_session = self
            .session
            .as_ref()
            .is_none_or(|s| s.key != key || s.epoch != epoch);
        let mut desired = if new_session {
            self.document
                .communities
                .get(key)
                .map(|values| roster(values))
                .transpose()?
                .unwrap_or_default()
        } else {
            self.session.as_ref().ok_or(INVALID)?.desired.clone()
        };
        // An actually enlisted new incarnation supersedes a saved reused numeric ID.
        // A lookup mismatch alone never replaces a saved identity.
        for identity in &live {
            desired.retain(|old| old.id != identity.id || old == identity);
            desired.insert(identity.clone());
        }
        if desired.len() > MAX_FOLLOWERS {
            return Err(INVALID);
        }
        self.session = Some(Session {
            key: key.into(),
            epoch,
            desired,
            live,
        });
        self.capture()
    }
    pub fn leave(&mut self) {
        self.session = None;
    }
    /// Record-level enlistment may precede actor streaming. Preserve that
    /// membership, but only actors actually present in this world confirm it.
    pub fn observe_confirmed(
        &mut self,
        key: &str,
        epoch: u64,
        enlisted: &[Identity],
        present: &[Identity],
    ) -> Result<(), i32> {
        let enlisted_set = roster(enlisted)?;
        let present = roster(present)?;
        if !present.is_subset(&enlisted_set) {
            return Err(INVALID);
        }
        self.observe(key, epoch, enlisted)?;
        self.session.as_mut().ok_or(INVALID)?.live = present;
        Ok(())
    }
    /// Native successful dismissal/death supplies exact identities, never an empty list diff.
    pub fn forget(&mut self, key: &str, epoch: u64, identities: &[Identity]) -> Result<(), i32> {
        let session = self.session.as_mut().ok_or(INVALID)?;
        if session.key != key || session.epoch != epoch {
            return Err(sod2se_abi::STALE);
        }
        for identity in identities {
            session.desired.remove(identity);
            session.live.remove(identity);
        }
        self.capture()
    }
    fn capture(&mut self) -> Result<(), i32> {
        let session = self.session.as_ref().ok_or(INVALID)?;
        if !self.document.communities.contains_key(&session.key)
            && self.document.communities.len() == MAX_COMMUNITIES
        {
            return Err(INVALID);
        }
        let values: Vec<_> = session.desired.iter().cloned().collect();
        if self.document.communities.get(&session.key) != Some(&values) {
            self.document
                .communities
                .insert(session.key.clone(), values);
            self.dirty = true;
        }
        Ok(())
    }
    pub fn pending(&self) -> Vec<Identity> {
        self.session
            .as_ref()
            .map(|s| s.desired.difference(&s.live).cloned().collect())
            .unwrap_or_default()
    }
    pub fn document(&self) -> &Document {
        &self.document
    }
    pub fn dirty(&self) -> bool {
        self.dirty
    }
    pub fn committed(&mut self) {
        self.dirty = false;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const A: &str = "11111111111111111111111111111111";
    const B: &str = "22222222222222222222222222222222";
    fn member(id: i32) -> Identity {
        Identity {
            id,
            narrative: 100 + id as u64,
            entity: 200 + id as u64,
        }
    }
    fn all() -> Vec<Identity> {
        vec![member(1), member(2), member(3)]
    }
    #[test]
    fn restart_restores_full_roster_and_does_not_duplicate_vanilla_member() {
        let mut first = Policy::new(Document::default()).unwrap();
        first.observe(A, 1, &all()).unwrap();
        let bytes = serde_json::to_vec(first.document()).unwrap();
        let mut next = Policy::new(serde_json::from_slice(&bytes).unwrap()).unwrap();
        next.observe(A, 1, &[member(1)]).unwrap();
        assert_eq!(next.pending(), vec![member(2), member(3)]);
        next.observe(A, 1, &[member(1), member(2)]).unwrap();
        assert_eq!(next.document().communities[A], all());
        next.observe(A, 1, &all()).unwrap();
        assert!(next.pending().is_empty());
    }
    #[test]
    fn ordinary_members_with_zero_narrative_fields_survive_reload_and_remain_isolated() {
        let ordinary: Vec<_> = (1..=3)
            .map(|id| Identity {
                id,
                narrative: 0,
                entity: 0,
            })
            .collect();
        let mut first = Policy::new(Document::default()).unwrap();
        first.observe(A, 1, &ordinary).unwrap();
        let bytes = serde_json::to_vec(first.document()).unwrap();
        let mut next = Policy::new(serde_json::from_slice(&bytes).unwrap()).unwrap();
        next.observe(A, 2, &ordinary[..1]).unwrap();
        assert_eq!(next.pending(), ordinary[1..]);
        assert_eq!(next.document().communities[A], ordinary);
        next.observe(B, 3, &ordinary[..1]).unwrap();
        assert!(
            next.pending().is_empty(),
            "same numeric IDs in another community must not restore"
        );
        next.observe(A, 4, &ordinary[..2]).unwrap();
        assert_eq!(next.pending(), ordinary[2..]);
        next.observe(A, 4, &ordinary).unwrap();
        assert!(next.pending().is_empty());
        next.forget(A, 4, &ordinary[1..2]).unwrap();
        assert_eq!(
            next.document().communities[A],
            vec![ordinary[0].clone(), ordinary[2].clone()]
        );
        let bound = Identity {
            narrative: 99,
            ..ordinary[2].clone()
        };
        assert_ne!(
            bound, ordinary[2],
            "zero fields do not permit a numeric-only identity fallback"
        );
        assert_eq!(
            Identity {
                id: -1,
                narrative: 0,
                entity: 0
            }
            .validate(),
            Err(INVALID)
        );
    }
    #[test]
    fn native_record_enlistment_is_saved_but_waits_for_actor_confirmation() {
        let mut policy = Policy::new(Document::default()).unwrap();
        policy.observe(A, 1, &all()).unwrap();
        policy.committed();
        policy.leave();
        policy
            .observe_confirmed(A, 2, &[member(1)], &[member(1)])
            .unwrap();
        assert_eq!(policy.pending(), vec![member(2), member(3)]);
        policy
            .observe_confirmed(A, 2, &all(), &[member(1)])
            .unwrap();
        assert_eq!(
            policy.pending(),
            vec![member(2), member(3)],
            "adding data does not mean an actor has loaded"
        );
        assert!(
            !policy.dirty(),
            "partial streaming must preserve the full saved document"
        );
        policy
            .observe_confirmed(A, 2, &all(), &[member(1), member(2)])
            .unwrap();
        assert_eq!(policy.pending(), vec![member(3)]);
        policy.observe_confirmed(A, 2, &all(), &all()).unwrap();
        assert!(policy.pending().is_empty());
        let before = policy.document().clone();
        assert_eq!(
            policy.observe_confirmed(A, 2, &[member(1)], &[member(9)]),
            Err(INVALID)
        );
        assert_eq!(policy.document(), &before);
    }
    #[test]
    fn loading_empty_snapshots_and_partial_failure_preserve_pending_roster() {
        let mut policy = Policy::new(Document::default()).unwrap();
        policy.observe(A, 1, &all()).unwrap();
        policy.leave();
        policy.observe(A, 2, &[]).unwrap();
        assert_eq!(policy.pending(), all());
        policy.observe(A, 2, &[member(1)]).unwrap();
        policy.leave();
        assert_eq!(policy.document().communities[A], all());
    }
    #[test]
    fn explicit_dismissal_and_death_do_not_return_after_restart() {
        let mut policy = Policy::new(Document::default()).unwrap();
        policy.observe(A, 1, &all()).unwrap();
        policy.forget(A, 1, &[member(2), member(3)]).unwrap();
        let mut next = Policy::new(policy.document().clone()).unwrap();
        next.observe(A, 1, &[member(1)]).unwrap();
        assert!(next.pending().is_empty());
        assert_eq!(next.document().communities[A], vec![member(1)]);
    }
    #[test]
    fn different_communities_and_reused_slots_are_isolated() {
        let mut policy = Policy::new(Document::default()).unwrap();
        policy.observe(A, 1, &all()).unwrap();
        policy.observe(B, 2, &[member(9)]).unwrap();
        assert!(policy.pending().is_empty());
        assert_eq!(policy.document().communities[A], all());
        policy.observe(A, 3, &[member(1)]).unwrap();
        assert_eq!(policy.pending(), vec![member(2), member(3)]);
        assert_eq!(policy.forget(B, 2, &[member(1)]), Err(sod2se_abi::STALE));
    }
    #[test]
    fn numeric_identity_reuse_requires_actual_new_enlistment() {
        let mut policy = Policy::new(Document::default()).unwrap();
        policy.observe(A, 1, &[member(2)]).unwrap();
        policy.leave();
        policy.observe(A, 2, &[]).unwrap();
        let replacement = Identity {
            entity: 900,
            ..member(2)
        };
        assert_eq!(policy.pending(), vec![member(2)]);
        policy
            .observe(A, 2, std::slice::from_ref(&replacement))
            .unwrap();
        assert_eq!(policy.document().communities[A], vec![replacement]);
    }
    #[test]
    fn malformed_future_duplicate_and_default_identities_refused() {
        let future = Document {
            format: 2,
            ..Document::default()
        };
        assert!(matches!(Policy::new(future), Err(UNSUPPORTED)));
        let mut duplicate = Document::default();
        duplicate
            .communities
            .insert(A.into(), vec![member(1), member(1)]);
        assert!(matches!(Policy::new(duplicate), Err(INVALID)));
        let mut policy = Policy::new(Document::default()).unwrap();
        assert_eq!(
            policy.observe(
                A,
                1,
                &[Identity {
                    id: -1,
                    narrative: 0,
                    entity: 0
                }]
            ),
            Err(INVALID)
        );
        assert!(!policy.dirty());
    }
}

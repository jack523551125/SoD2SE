use sod2se_services::{native_settings::{Session, Reply}, ui::Model};
use serde_json::json;

fn model(risk:&str) -> Model {
    serde_json::from_value(json!({"presentation":2,"chrome":["已保存"],"revision":1,
        "settings_revision":0,"language":"zh-CN","pages":[{"id":"example","name":"示例","description":"说明","loaded":true,"version":"1.0"}],
        "options":[{"module":"example","id":"value","page":0,"label":"参数","description":"说明","kind":1,
        "value":-3,"minimum":-10,"maximum":10,"default_value":0,"restart":true,"risk":risk}]})).unwrap()
}
fn number(r:Reply)->i32 {if let Reply::Number(n)=r{n}else{panic!("expected numeric status")}}
#[test]
fn consent_is_revision_bound_single_use_and_legacy_refuses() {
    let mut s=Session::default();let t=s.open_v2(vec![("mcm.settings".into(),model("dangerous"))]);
    assert!(number(s.query(15,t,0,5))<0);
    let nonce=number(s.query_v2(25,t,0,5,0));assert!(nonce>0);
    assert!(number(s.query_v2(26,t,nonce,0,1))<0); // external Registry edit
    assert!(number(s.query_v2(26,t,nonce,0,0))<0); // consumed even on refusal
    let nonce=number(s.query_v2(25,t,0,5,0));
    match s.query_v2(26,t,nonce,0,0) {Reply::Edit{value,..}=>{assert_eq!(value["risk_ack"],true);assert_eq!(value["value"],5)},_=>panic!("expected acknowledged edit")}
    assert!(number(s.query_v2(26,t,nonce,0,0))<0);
    assert!(number(s.query_v2(25,t,0,6,0))<0); // in flight
    s.complete(t,-4,"失败".into(),0).unwrap();
    assert!(matches!(s.query_v2(10,t,0,0,0),Reply::Text(v) if v=="-3"));
}
#[test]
fn metadata_defaults_negative_values_and_stale_views() {
    let mut s=Session::default();let mut m=model("normal");let t=s.open_v2(vec![("mcm.settings".into(),m.clone())]);
    assert!(matches!(s.query_v2(20,t,0,0,0),Reply::Text(v) if v=="已保存"));
    assert!(matches!(s.query_v2(22,t,0,0,0),Reply::Text(v) if v=="1.0"));
    assert!(matches!(s.query_v2(23,t,0,0,0),Reply::Text(v) if v=="0"));
    assert!(matches!(s.query_v2(10,t,0,0,0),Reply::Text(v) if v=="-3")); // not BUSY
    assert!(matches!(s.query_v2(15,t,0,0,0),Reply::Edit{..}));
    s.complete(t,0,"已保存".into(),1).unwrap();
    m.revision=2;m.settings_revision=1;m.options[0].value=0;s.refresh(vec![("mcm.settings".into(),m.clone())]);
    assert_eq!(number(s.query(18,t,0,0)),0);
    m.options[0].value=2;m.settings_revision=2;m.revision=3;s.refresh(vec![("mcm.settings".into(),m)]);
    assert_eq!(number(s.query(18,t,0,0)),-7);
    assert!(number(s.query_v2(15,t,0,1,2))<0);
}
#[test]
fn consent_cancel_and_reopen_refuse() {
    let mut s=Session::default();let m=model("dangerous");let t=s.open_v2(vec![("mcm.settings".into(),m.clone())]);
    let n=number(s.query_v2(25,t,0,5,0));s.query_v2(27,t,0,0,0);
    assert!(number(s.query_v2(26,t,n,0,0))<0);
    let n=number(s.query_v2(25,t,0,5,0));let next=s.open_v2(vec![("mcm.settings".into(),m)]);
    assert!(number(s.query_v2(26,next,n,0,0))<0);
    assert!(number(s.query_v2(26,t,n,0,0))<0);
}

#[test]
fn legacy_open_cannot_grant_v2_consent() {
    let mut s=Session::default();let t=s.open(vec![("mcm.settings".into(),model("dangerous"))]);
    assert!(number(s.query_v2(25,t,0,5,0))<0);
    assert!(number(s.query(15,t,0,5))<0);
}
